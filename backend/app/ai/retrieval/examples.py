"""Few-shot style-example retrieval for the draft writer.

Wraps ``HybridRetriever`` with two rules a generic passage retriever has no
reason to know about: an example of the wrong ``correspondence_type`` is
worse than no example at all (it teaches the wrong letter shape), and two
examples from the same institution teach the writer to imitate that
institution's letterhead rather than the structure shared across all of
them.
"""

import logging
from dataclasses import dataclass

from app.ai.retrieval.hybrid import HybridRetriever

logger = logging.getLogger(__name__)

#: Fetched candidates per requested example, before the institution-diversity
#: filter narrows them down. Wide enough that a couple of same-kurum hits at
#: the top of the ranking don't starve the final selection.
_CANDIDATE_MULTIPLIER = 3


@dataclass(frozen=True)
class StyleExample:
    """One retrieved official-letter example, for the writer/reviser prompt."""

    text: str
    correspondence_type: str
    niyet: str
    kurum: str
    baslik: str


class ExampleRetriever:
    """Retrieves style-reference examples for the draft writer."""

    def __init__(self, retriever: HybridRetriever):
        self._retriever = retriever

    async def retrieve(
        self,
        *,
        query: str,
        correspondence_type: str,
        limit: int = 2,
        char_budget: int = 4000,
    ) -> list[StyleExample]:
        """Fetch up to ``limit`` style examples for a given letter type.

        Never raises: retrieval is an optional quality boost for the draft
        writer, not a dependency, so any failure (Qdrant down, embedding
        call failing, an empty corpus) degrades to an empty list rather than
        propagating.

        Args:
            query: Short topic query -- typically subject + user
                instructions, not the full brief.
            correspondence_type: Hard filter; only examples of this exact
                type are considered.
            limit: Maximum examples to return.
            char_budget: Ceiling on the combined character length of the
                returned examples' text. The longest example is dropped
                first when the combined text would exceed it.

        Returns:
            Up to ``limit`` examples, ranked and diversified by institution,
            within ``char_budget``. Empty on no match or on failure.
        """
        if not query.strip() or not correspondence_type:
            return []

        try:
            documents = await self._retriever.retrieve(
                query,
                limit=limit * _CANDIDATE_MULTIPLIER,
                filter_dict={"correspondence_type": correspondence_type},
            )
        except Exception:
            logger.exception(
                "Style example retrieval failed for correspondence_type=%s.",
                correspondence_type,
            )
            return []

        examples: list[StyleExample] = []
        seen_kurum: set[str] = set()
        for document in documents:
            metadata = document.metadata
            kurum = metadata.get("kurum") or ""
            if kurum and kurum in seen_kurum:
                continue
            examples.append(
                StyleExample(
                    text=document.page_content,
                    correspondence_type=metadata.get(
                        "correspondence_type", correspondence_type
                    ),
                    niyet=metadata.get("niyet", ""),
                    kurum=kurum,
                    baslik=metadata.get("baslik", ""),
                )
            )
            if kurum:
                seen_kurum.add(kurum)
            if len(examples) >= limit:
                break

        return _apply_char_budget(examples, char_budget)


def _apply_char_budget(
    examples: list[StyleExample], char_budget: int
) -> list[StyleExample]:
    """Drop the longest example first until the combined text fits the budget.

    Always keeps at least one example (even if it alone exceeds the budget)
    -- one oversized example still beats zero, and DraftPolicy's budget
    already leaves headroom in the writer's overall context window.
    """
    kept = list(examples)
    while len(kept) > 1 and sum(len(example.text) for example in kept) > char_budget:
        longest = max(kept, key=lambda example: len(example.text))
        kept.remove(longest)
    return kept
