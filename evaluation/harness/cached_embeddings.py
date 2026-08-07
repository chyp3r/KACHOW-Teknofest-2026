"""A precomputed, dependency-free stand-in for the real embeddings client.

``make eval`` runs with ``--no-deps`` and touches no infrastructure -- that
is the whole point of the suite (see ``Makefile``'s comment on the target).
Measuring the semantic rung (``app.ai.semantic.prototype_matcher``) for real
means embedding every gold-set message, which needs a live embeddings
service. The way out is the same one ``scripts/build_prototypes.py`` uses for
the prototype phrasings themselves: embed once, offline, and cache the
vectors on disk; the eval run then only does a dictionary lookup.

A cache miss is a loud failure, not a silent fallback -- a gold-set message
this cache doesn't know about would otherwise make the semantic rung silently
unavailable for that one case, exactly the kind of silent degradation this
whole evaluation chain exists to catch (see ``ROUTER_SEMANTIC_AVAILABLE``).
"""

import json
from pathlib import Path
from typing import List, Optional

from app.ai.embeddings.models import BaseEmbeddingsClient

#: Written by scripts/build_eval_embeddings.py.
DEFAULT_CACHE_PATH = (
    Path(__file__).resolve().parents[2] / "evaluation" / "datasets" / "intent_embeddings.json"
)


class CachedEmbeddingsClient(BaseEmbeddingsClient):
    """Looks up precomputed vectors by exact message text; never calls a model."""

    def __init__(self, cache_path: Optional[Path] = None) -> None:
        """Load the cache.

        Args:
            cache_path: Override for the cache file, for tests.

        Raises:
            FileNotFoundError: When the cache hasn't been built yet.
        """
        path = cache_path or DEFAULT_CACHE_PATH
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found. Run: docker compose run --rm --no-deps "
                "backend python scripts/build_eval_embeddings.py"
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.model = payload["model"]
        self._vectors: dict[str, List[float]] = {
            entry["text"]: entry["vector"] for entry in payload["embeddings"]
        }

    async def embed_query(self, text: str) -> List[float]:
        """Look up the cached vector for ``text``.

        Raises:
            KeyError: When ``text`` isn't in the cache -- rerun
                ``scripts/build_eval_embeddings.py`` after editing the gold set.
        """
        try:
            return self._vectors[text]
        except KeyError:
            raise KeyError(
                f"No cached embedding for {text!r}. Rerun "
                "scripts/build_eval_embeddings.py after editing the gold set."
            ) from None

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Look up cached vectors for every text. Unused by the intent suite."""
        return [await self.embed_query(text) for text in texts]

    def missing(self, texts: List[str]) -> set[str]:
        """Report which of ``texts`` have no cached vector.

        ``PrototypeMatcher.match`` catches every exception from
        ``embed_query`` and degrades to "semantic layer skipped for this
        turn" -- correct for a real embeddings outage, but it would turn a
        stale eval cache into a silent per-case degradation instead of a
        loud failure. Callers check this up front instead of relying on that
        catch to surface a miss.
        """
        return {text for text in texts if text not in self._vectors}
