"""Bounded, observable prompt assembly.

Context used to be built inline in three separate places (the assist step,
the draft brief, the analysis prompt), each with its own ad-hoc truncation
and none of them measuring anything against the model's real context
window -- see ``app/ai/llms/base.py``'s ``count_tokens``. This module
replaces "concatenate strings and hope" with an explicit budget: required
pieces are never dropped, optional pieces are kept in priority order until
the budget runs out, and whatever didn't fit is reported on the result
instead of silently truncated.
"""

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from app.ai.context.budget import TokenBudget
from app.ai.llms.base import BaseLLMClient

logger = logging.getLogger(__name__)

#: Shrinks `text` to fit `budget_tokens`, returning the (possibly still
#: too-large) result. Tried before a block is dropped outright.
Compressor = Callable[[str, int], str]


class ContextBudgetExceeded(Exception):
    """The context's ``required`` blocks alone exceed the available budget.

    Raised rather than silently overflowing the model's context window --
    the previous behaviour (concatenate everything, let Ollama truncate from
    the beginning) is exactly the failure mode this module exists to end.
    """


@dataclass(frozen=True)
class ContextBlock:
    """One named, independently sizeable piece of a prompt.

    Attributes:
        id: Stable name. Used for observability (``AssembledContext.dropped``
            / ``.compressed``) and to look the rendered text back up by name.
        priority: Drop order when the budget is tight -- lower is dropped
            first. Blocks sharing a priority are dropped in the order they
            were passed to ``ContextBuilder.build``. Irrelevant for
            ``required`` blocks.
        render: Produces the block's text. Deferred (an async callable
            rather than a plain string) so a block the caller decides not to
            include for this turn never pays its own formatting cost.
        compressor: Optional fallback tried before dropping an optional block,
            or before a required block that doesn't fit raises
            ``ContextBudgetExceeded``: ``compressor(text, budget_tokens) -> str``.
        required: Never dropped. Still passed through ``compressor`` first if
            it doesn't fit on its own -- "required" means this content must
            be represented, not that this exact text must be sent verbatim.
    """

    id: str
    priority: int
    render: Callable[[], Awaitable[str]]
    compressor: Optional[Compressor] = None
    required: bool = False


@dataclass(frozen=True)
class AssembledContext:
    """The rendered result of one ``ContextBuilder.build`` call.

    Attributes:
        texts: Final text per included block id (dropped blocks are absent).
        dropped: Block ids that did not fit, even after compression.
        compressed: Block ids kept only after their compressor ran.
        total_tokens: Combined size of every block in ``texts``.
    """

    texts: dict[str, str]
    dropped: tuple[str, ...]
    compressed: tuple[str, ...]
    total_tokens: int

    def get(self, block_id: str, default: str = "") -> str:
        """Return a block's text, or ``default`` when it was dropped/absent."""
        return self.texts.get(block_id, default)


class ContextBuilder:
    """Assembles a bounded prompt from independently-sized blocks.

    Renders every block, keeps ``required`` ones unconditionally, then keeps
    optional ones in ascending ``priority`` order until the budget runs
    out -- compressing (when a compressor is configured) or dropping the
    rest. Nothing is silently truncated: what didn't fit is reported on the
    result, not swallowed.
    """

    def __init__(self, llm_client: BaseLLMClient):
        """Initialize the builder.

        Args:
            llm_client: Supplies ``count_tokens`` -- the same estimator the
                actual generation call will be sized against, so the budget
                this builder enforces matches what the provider sees.
        """
        self._llm_client = llm_client

    async def build(
        self, blocks: list[ContextBlock], budget: TokenBudget
    ) -> AssembledContext:
        """Render and fit ``blocks`` into ``budget``.

        Args:
            blocks: The candidate blocks for this prompt.
            budget: The token budget to fit them into.

        Returns:
            The assembled context.

        Raises:
            ContextBudgetExceeded: The required blocks alone don't fit.
        """
        rendered: dict[str, str] = {}
        for block in blocks:
            rendered[block.id] = await block.render()

        required = [b for b in blocks if b.required]
        optional = sorted(
            (b for b in blocks if not b.required), key=lambda b: b.priority
        )

        count_tokens = self._llm_client.count_tokens

        # A required block never gets dropped, but it still gets a chance to
        # compress before the whole call fails outright -- required means
        # "this content must be represented", not "this exact text must be
        # sent verbatim no matter what".
        texts: dict[str, str] = {}
        compressed: list[str] = []
        required_tokens = 0
        for block in required:
            text = rendered[block.id]
            cost = count_tokens(text)
            available_for_block = budget.available - required_tokens
            if cost > available_for_block and block.compressor is not None:
                shrunk = block.compressor(text, max(available_for_block, 0))
                shrunk_cost = count_tokens(shrunk)
                if shrunk_cost < cost:
                    text, cost = shrunk, shrunk_cost
                    compressed.append(block.id)
            texts[block.id] = text
            required_tokens += cost

        if required_tokens > budget.available:
            raise ContextBudgetExceeded(
                f"Required context blocks need {required_tokens} tokens; "
                f"only {budget.available} available."
            )

        dropped: list[str] = []
        remaining = budget.available - required_tokens

        for block in optional:
            text = rendered[block.id]
            cost = count_tokens(text)

            if cost <= remaining:
                texts[block.id] = text
                remaining -= cost
                continue

            if block.compressor is not None and remaining > 0:
                shrunk = block.compressor(text, remaining)
                shrunk_cost = count_tokens(shrunk)
                if shrunk_cost <= remaining:
                    texts[block.id] = shrunk
                    compressed.append(block.id)
                    remaining -= shrunk_cost
                    continue

            dropped.append(block.id)
            logger.info("Context block '%s' dropped (budget exhausted).", block.id)

        total_tokens = sum(count_tokens(text) for text in texts.values())
        return AssembledContext(
            texts=texts,
            dropped=tuple(dropped),
            compressed=tuple(compressed),
            total_tokens=total_tokens,
        )
