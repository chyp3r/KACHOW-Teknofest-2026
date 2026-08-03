"""Matches a message against precomputed class prototypes by cosine similarity.

Layer 2 of the decision ladder: it sits between the lexical rules (~0 ms, blind
to paraphrase) and the fast-tier model (~1-3 s for a single structured label).
Only messages the lexical layer abstained on reach it.

Why this is worth a layer at all
--------------------------------
One ``embed_query`` on a short message costs ~21 ms at p50 and ~29 ms at p95, measured against a model
that is already resident and warm -- ``HybridRetriever`` calls the same service
on every legislation search. A single fast-tier label costs 1-3 s once the JSON
schema, Pydantic validation and a possible retry are counted. So a paraphrase
resolved here costs a few percent of what it costs one rung up.

Why it never decides alone
--------------------------
A prototype hit needs **both** a high absolute similarity and a clear gap to the
runner-up. Cosine similarity between short Turkish sentences is compressed --
unrelated official-register sentences routinely sit around 0.6 -- so an absolute
threshold alone would fire constantly, and a margin alone would fire on two
equally-bad matches that happen to differ. Failing either check means falling
through to the model, which is the correct outcome for a genuinely unclear
message.

Staleness
---------
The vector file records the embedding model, its dimension and the policy
version that produced it. On any mismatch the matcher disables itself and every
message escalates as before. Deciding from vectors built by a different model is
worse than paying for a model call: it is confidently wrong rather than slow.
"""

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from app.ai.embeddings.models import BaseEmbeddingsClient
from app.ai.policy import POLICY_VERSION, get_policy
from app.core.config import settings

logger = logging.getLogger(__name__)

__all__ = ["SemanticMatch", "PrototypeMatcher", "PROTOTYPE_DIR"]

#: Where ``scripts/build_prototypes.py`` writes its output.
#:
#: Relative to the working directory, matching ``MEVZUAT_CORPUS_DIR``. Deriving
#: it from ``__file__`` instead looked tidier and was wrong: in the container the
#: package root *is* the working directory, so walking up past it landed on `/`
#: and the vectors were written outside every mount, silently discarded when the
#: container exited.
PROTOTYPE_DIR = Path(settings.PROTOTYPE_DIR)


@dataclass(frozen=True)
class SemanticMatch:
    """One family's best label for a message.

    Attributes:
        label: The winning class.
        similarity: Cosine similarity to that class's best prototype.
        runner_up_gap: How far ahead of the second-best class it sits.
        decisive: Whether both thresholds were cleared. A non-decisive match is
            still returned -- it is useful evidence for a log line -- but must
            not be acted on.
    """

    label: str
    similarity: float
    runner_up_gap: float
    decisive: bool


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity of two vectors, 0.0 when either has no magnitude."""
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class PrototypeMatcher:
    """Loads precomputed prototype vectors and scores messages against them."""

    def __init__(
        self,
        embeddings_client: BaseEmbeddingsClient,
        *,
        model_name: str,
        prototype_dir: Optional[Path] = None,
    ) -> None:
        """Load the prototype vectors for every family.

        Args:
            embeddings_client: Used only to embed the incoming message. No
                prototype is embedded at request time.
            model_name: The embedding model in use, checked against the stamp
                on each vector file.
            prototype_dir: Override for the vector directory, for tests.
        """
        self._client = embeddings_client
        self._model_name = model_name
        self._dir = prototype_dir or PROTOTYPE_DIR
        self._families: dict[str, list[tuple[str, list[float]]]] = {}
        self._load()

    @property
    def available(self) -> bool:
        """Whether any family loaded successfully."""
        return bool(self._families)

    def _load(self) -> None:
        """Read every family's vector file, skipping stale or unreadable ones."""
        if not self._dir.exists():
            logger.info(
                "No prototype directory at %s; semantic matching disabled. "
                "Run scripts/build_prototypes.py to enable it.",
                self._dir,
            )
            return

        for path in sorted(self._dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Unreadable prototype file %s; skipping.", path)
                continue

            if payload.get("model") != self._model_name:
                logger.warning(
                    "Prototype file %s was built with model %r but %r is active; "
                    "skipping rather than matching against stale vectors.",
                    path.name,
                    payload.get("model"),
                    self._model_name,
                )
                continue

            if payload.get("policy_version") != POLICY_VERSION:
                logger.warning(
                    "Prototype file %s was built under policy %s but %s is active; "
                    "skipping.",
                    path.name,
                    payload.get("policy_version"),
                    POLICY_VERSION,
                )
                continue

            entries = [
                (entry["label"], entry["vector"])
                for entry in payload.get("prototypes", [])
                if entry.get("vector")
            ]
            if entries:
                self._families[payload["family"]] = entries

        if self._families:
            logger.info(
                "Prototype matcher loaded families: %s", sorted(self._families)
            )

    async def match(self, text: str, family: str) -> Optional[SemanticMatch]:
        """Score a message against one family's prototypes.

        Never raises. An embeddings outage degrades this layer to a no-op and
        the caller escalates exactly as it did before the layer existed.

        Args:
            text: The user's message.
            family: The family to score against.

        Returns:
            The best match, or None when the family is unavailable, the text is
            empty, or the embedding call failed.
        """
        entries = self._families.get(family)
        if not entries or not (text or "").strip():
            return None

        try:
            vector = await self._client.embed_query(text)
        except Exception:
            logger.warning(
                "Embedding call failed; semantic matching skipped for this turn.",
                exc_info=True,
            )
            return None

        best_per_label: dict[str, float] = {}
        for label, prototype in entries:
            score = _cosine(vector, prototype)
            if score > best_per_label.get(label, -1.0):
                best_per_label[label] = score

        if not best_per_label:
            return None

        ranked = sorted(best_per_label.items(), key=lambda item: (-item[1], item[0]))
        label, similarity = ranked[0]
        gap = similarity - ranked[1][1] if len(ranked) > 1 else similarity

        policy = get_policy().semantic
        decisive = (
            similarity >= policy.decisive_similarity and gap >= policy.decisive_margin
        )

        return SemanticMatch(
            label=label,
            similarity=round(similarity, 4),
            runner_up_gap=round(gap, 4),
            decisive=decisive,
        )
