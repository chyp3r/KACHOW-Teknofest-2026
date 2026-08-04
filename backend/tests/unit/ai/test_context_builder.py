"""Unit tests for the bounded, observable context assembler.

Context used to be built by concatenating strings with no budget at all --
these tests prove the replacement actually enforces one: required blocks
always survive, optional blocks are kept in priority order until the budget
runs out, and whatever didn't fit is reported rather than silently dropped
into an overflowing prompt.
"""

import pytest

from app.ai.context.builder import ContextBlock, ContextBudgetExceeded, ContextBuilder
from app.ai.context.budget import TokenBudget
from app.ai.context.compress import truncate_with_marker


def _const(text: str):
    async def _render() -> str:
        return text

    return _render


@pytest.mark.asyncio
async def test_every_block_fits_when_the_budget_is_generous(fake_llm):
    builder = ContextBuilder(fake_llm)
    blocks = [
        ContextBlock(id="system", priority=0, render=_const("Sen bir asistansın."), required=True),
        ContextBlock(id="history", priority=10, render=_const("Kullanıcı: merhaba")),
        ContextBlock(id="doc", priority=20, render=_const("Belge özeti burada.")),
    ]

    result = await builder.build(blocks, TokenBudget(total=8192))

    assert result.dropped == ()
    assert result.compressed == ()
    assert set(result.texts) == {"system", "history", "doc"}


@pytest.mark.asyncio
async def test_required_blocks_are_never_dropped_even_under_pressure(fake_llm):
    builder = ContextBuilder(fake_llm)
    huge_optional = "kelime " * 5000  # far larger than the tiny budget below
    blocks = [
        ContextBlock(id="system", priority=0, render=_const("Zorunlu sistem promptu."), required=True),
        ContextBlock(id="history", priority=10, render=_const(huge_optional)),
    ]

    result = await builder.build(blocks, TokenBudget(total=20))

    assert "system" in result.texts
    assert "history" in result.dropped
    assert "history" not in result.texts


@pytest.mark.asyncio
async def test_a_required_block_compresses_before_raising(fake_llm):
    builder = ContextBuilder(fake_llm)
    blocks = [
        ContextBlock(
            id="document_context",
            priority=0,
            render=_const("A" * 3000),
            compressor=truncate_with_marker,
            required=True,
        ),
    ]

    result = await builder.build(blocks, TokenBudget(total=50))

    assert "document_context" in result.compressed
    assert "document_context" in result.texts
    assert len(result.texts["document_context"]) < 3000


@pytest.mark.asyncio
async def test_required_blocks_exceeding_the_budget_raise_instead_of_overflowing(fake_llm):
    builder = ContextBuilder(fake_llm)
    blocks = [
        ContextBlock(
            id="system", priority=0, render=_const("kelime " * 5000), required=True
        ),
    ]

    with pytest.raises(ContextBudgetExceeded):
        await builder.build(blocks, TokenBudget(total=5))


@pytest.mark.asyncio
async def test_lower_priority_blocks_are_dropped_first(fake_llm):
    builder = ContextBuilder(fake_llm)
    filler = "kelime " * 40  # sized so exactly one of the two optionals fits
    blocks = [
        ContextBlock(id="system", priority=0, render=_const("s"), required=True),
        ContextBlock(id="low", priority=10, render=_const(filler)),
        ContextBlock(id="high", priority=20, render=_const(filler)),
    ]
    tokens_per_filler = fake_llm.count_tokens(filler)
    budget = TokenBudget(total=fake_llm.count_tokens("s") + tokens_per_filler + 2)

    result = await builder.build(blocks, budget)

    assert "low" in result.texts
    assert "high" in result.dropped


@pytest.mark.asyncio
async def test_a_compressor_is_tried_before_dropping(fake_llm):
    builder = ContextBuilder(fake_llm)
    long_text = "A" * 3000

    blocks = [
        ContextBlock(id="system", priority=0, render=_const("s"), required=True),
        ContextBlock(
            id="doc",
            priority=10,
            render=_const(long_text),
            compressor=truncate_with_marker,
        ),
    ]
    # Big enough for a compressed version, nowhere near enough for the raw text.
    budget = TokenBudget(total=fake_llm.count_tokens("s") + 50)

    result = await builder.build(blocks, budget)

    assert "doc" in result.compressed
    assert "doc" not in result.dropped
    assert len(result.texts["doc"]) < len(long_text)
    assert "kısaltıldı" in result.texts["doc"]


@pytest.mark.asyncio
async def test_a_block_with_zero_remaining_budget_is_dropped_without_compressing(fake_llm):
    builder = ContextBuilder(fake_llm)
    blocks = [
        ContextBlock(id="system", priority=0, render=_const("s"), required=True),
        ContextBlock(
            id="doc",
            priority=10,
            render=_const("A" * 3000),
            compressor=truncate_with_marker,
        ),
    ]
    # The required block alone exactly exhausts the budget -- nothing left
    # for "doc" even after compression, so it must be dropped outright.
    budget = TokenBudget(total=fake_llm.count_tokens("s"))

    result = await builder.build(blocks, budget)

    assert "doc" in result.dropped
    assert "doc" not in result.compressed
    assert "doc" not in result.texts


@pytest.mark.asyncio
async def test_reserved_completion_budget_shrinks_what_the_prompt_may_use(fake_llm):
    builder = ContextBuilder(fake_llm)
    filler = "kelime " * 40
    blocks = [
        ContextBlock(id="system", priority=0, render=_const("s"), required=True),
        ContextBlock(id="doc", priority=10, render=_const(filler)),
    ]
    exact_fit_total = fake_llm.count_tokens("s") + fake_llm.count_tokens(filler)

    fits = await builder.build(blocks, TokenBudget(total=exact_fit_total))
    assert "doc" in fits.texts

    starved = await builder.build(
        blocks, TokenBudget(total=exact_fit_total, reserved_for_completion=1)
    )
    assert "doc" in starved.dropped


def test_truncate_with_marker_leaves_short_text_untouched():
    assert truncate_with_marker("kısa metin", budget_tokens=1000) == "kısa metin"


def test_truncate_with_marker_keeps_head_and_tail():
    text = "BAŞ" + ("x" * 5000) + "SON"
    result = truncate_with_marker(text, budget_tokens=50)

    assert result.startswith("BAŞ")
    assert result.endswith("SON")
    assert "kısaltıldı" in result
    assert len(result) < len(text)
