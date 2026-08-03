"""Integration-style tests for the draft graph's reflexion loop.

The former single-pass "writer -> LLM editor" pipeline had no path back to the
writer, so a low-scoring draft was only ever flagged, never repaired. These
tests exercise the actual compiled graph (writer/reviser streaming is mocked,
everything else -- routing, the deterministic verifier, state accumulation --
runs for real) to prove the loop only fires when a defect is text-revisable,
stops at MAX_DRAFT_ATTEMPTS, and short-circuits to a human question when the
writer leaves an explicit placeholder instead.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.agents.reviser import ReviserAgent
from app.ai.agents.writer import WriterAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.reasoning_levels import get_reasoning_level_preset
from app.ai.workflows.draft_graph import (
    MAX_DRAFT_ATTEMPTS,
    _resolve_free_text_client,
    create_draft_graph,
)
from app.core.config import settings
from app.core.enums.reasoning_level import ReasoningLevel

SOURCE_DOCUMENT = "Sayı: E-1-1, Tarih: 30.07.2026 tarihli evrak."

BAD_DRAFT = "Bu bir taslaktır ve hiçbir resmî unsur içermez."

GOOD_DRAFT = (
    "Konu: Test Konusu\n"
    "Sayı: E-1-1\n"
    "Tarih: 30.07.2026\n\n"
    "Sayın Makam,\n\n"
    "Arz ederim.\n\n"
    "Ali Veli\nGenel Müdür"
)

DRAFT_WITH_PLACEHOLDER = (
    "Konu: Test Konusu\n"
    "Sayı: E-1-1\n"
    "Tarih: 30.07.2026\n\n"
    "Sayın [MUHATAP],\n\n"
    "Arz ederim.\n\n"
    "Ali Veli\nGenel Müdür"
)

BASE_STATE = {
    "source_document": SOURCE_DOCUMENT,
    "classification": {
        "document_type_label": "Resmî Yazı",
        "summary": "Test evrakı.",
        "fields": {},
        "missing_fields": [],
    },
    "correspondence_type": "cover_letter",
    "context": "İlgili mevzuat metni burada.",
    "instructions": "Test talimatı.",
}


async def _one_chunk(text: str):
    yield text


@pytest.fixture(autouse=True)
def _disable_judge(monkeypatch):
    """Isolates the reflexion loop's routing from the judge call: these tests
    are about the deterministic-defect -> revise -> writer mechanics, not the
    hybrid gate (see test_llm_judge.py for that)."""
    monkeypatch.setattr(settings, "DRAFT_JUDGE_ENABLED", False)


@pytest.mark.asyncio
async def test_missing_structure_triggers_exactly_one_revision_then_completes():
    graph = create_draft_graph(MagicMock(spec=BaseLLMClient))

    with (
        patch.object(WriterAgent, "stream") as mock_writer,
        patch.object(ReviserAgent, "stream") as mock_reviser,
    ):
        mock_writer.side_effect = lambda **kwargs: _one_chunk(BAD_DRAFT)
        mock_reviser.side_effect = lambda **kwargs: _one_chunk(GOOD_DRAFT)

        result = await graph.ainvoke(BASE_STATE)

    assert mock_writer.call_count == 1
    assert mock_reviser.call_count == 1
    assert result["attempts"] == 2
    assert result["draft"] == GOOD_DRAFT
    assert result["status"] == "COMPLETED"
    assert len(result["attempt_history"]) == 2


@pytest.mark.asyncio
async def test_a_placeholder_short_circuits_to_needs_input_after_one_writer_call():
    """An explicit [...] placeholder means the writer already told the system
    it doesn't know the value -- retrying produces the same gap or a guess,
    so this must go straight to a human question, never through revise."""
    graph = create_draft_graph(MagicMock(spec=BaseLLMClient))

    with (
        patch.object(WriterAgent, "stream") as mock_writer,
        patch.object(ReviserAgent, "stream") as mock_reviser,
    ):
        mock_writer.side_effect = lambda **kwargs: _one_chunk(DRAFT_WITH_PLACEHOLDER)

        result = await graph.ainvoke(BASE_STATE)

    assert mock_writer.call_count == 1
    mock_reviser.assert_not_called()
    assert result["attempts"] == 1
    assert result["status"] == "NEEDS_INPUT"
    assert result["missing_information"]
    assert result["missing_information"][0]["key"] == "muhatap"


@pytest.mark.asyncio
async def test_attempts_stop_at_the_cap_even_when_still_revisable():
    graph = create_draft_graph(MagicMock(spec=BaseLLMClient))

    with (
        patch.object(WriterAgent, "stream") as mock_writer,
        patch.object(ReviserAgent, "stream") as mock_reviser,
    ):
        mock_writer.side_effect = lambda **kwargs: _one_chunk(BAD_DRAFT)
        mock_reviser.side_effect = lambda **kwargs: _one_chunk(BAD_DRAFT)

        result = await graph.ainvoke(BASE_STATE)

    assert mock_writer.call_count == 1
    assert mock_reviser.call_count == 1
    assert result["attempts"] == MAX_DRAFT_ATTEMPTS
    assert result["status"] == "NEEDS_HUMAN_APPROVAL"


@pytest.mark.asyncio
async def test_a_clean_first_draft_never_reaches_the_reviser():
    graph = create_draft_graph(MagicMock(spec=BaseLLMClient))

    with (
        patch.object(WriterAgent, "stream") as mock_writer,
        patch.object(ReviserAgent, "stream") as mock_reviser,
    ):
        mock_writer.side_effect = lambda **kwargs: _one_chunk(GOOD_DRAFT)

        result = await graph.ainvoke(BASE_STATE)

    mock_reviser.assert_not_called()
    assert result["attempts"] == 1
    assert result["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_writer_exception_ends_the_run_without_reaching_verify():
    graph = create_draft_graph(MagicMock(spec=BaseLLMClient))

    async def _raise(**kwargs):
        raise RuntimeError("model unavailable")
        yield  # pragma: no cover - makes this an async generator function

    with patch.object(WriterAgent, "stream") as mock_writer:
        mock_writer.side_effect = _raise

        result = await graph.ainvoke(BASE_STATE)

    assert result["status"] == "FAILED"
    assert "Taslak üretilemedi" in result["error"]
    # verify_node never ran, so nothing verification-specific was ever set.
    assert "verification" not in result


@pytest.mark.asyncio
async def test_missing_source_document_fails_before_any_generation_call():
    graph = create_draft_graph(MagicMock(spec=BaseLLMClient))
    state = {**BASE_STATE, "source_document": ""}

    with patch.object(WriterAgent, "stream") as mock_writer:
        result = await graph.ainvoke(state)

    mock_writer.assert_not_called()
    assert result["status"] == "FAILED"


# --- Reasoning-level awareness -----------------------------------------


def test_resolve_free_text_client_uses_fast_tier_only_for_the_fast_level():
    quality = MagicMock(spec=BaseLLMClient, name="quality")
    fast = MagicMock(spec=BaseLLMClient, name="fast")

    fast_preset = get_reasoning_level_preset(ReasoningLevel.FAST)
    balanced_preset = get_reasoning_level_preset(ReasoningLevel.BALANCED)
    deep_preset = get_reasoning_level_preset(ReasoningLevel.DEEP)

    assert _resolve_free_text_client(fast_preset, quality, fast) is fast
    assert _resolve_free_text_client(balanced_preset, quality, fast) is quality
    assert _resolve_free_text_client(deep_preset, quality, fast) is quality
    # No fast_llm_client configured (OLLAMA_FAST_MODEL unset) -> falls back to
    # the quality client rather than raising or using None.
    assert _resolve_free_text_client(fast_preset, quality, None) is quality


@pytest.mark.asyncio
async def test_fast_level_stops_after_one_attempt_and_skips_the_judge():
    graph = create_draft_graph(
        MagicMock(spec=BaseLLMClient), MagicMock(spec=BaseLLMClient)
    )
    state = {**BASE_STATE, "reasoning_level": "fast"}

    with (
        patch.object(WriterAgent, "stream") as mock_writer,
        patch.object(ReviserAgent, "stream") as mock_reviser,
        patch(
            "app.ai.workflows.draft_graph.judge_draft", new_callable=AsyncMock
        ) as mock_judge_draft,
    ):
        mock_writer.side_effect = lambda **kwargs: _one_chunk(BAD_DRAFT)

        result = await graph.ainvoke(state)

    assert mock_writer.call_count == 1
    assert mock_writer.call_args.kwargs["reasoning"] is False
    mock_reviser.assert_not_called()
    # fast forces the judge off regardless of settings.DRAFT_JUDGE_ENABLED.
    mock_judge_draft.assert_not_called()
    assert result["attempts"] == 1
    assert result["status"] == "NEEDS_HUMAN_APPROVAL"
    assert result["reasoning_level"] == "fast"


@pytest.mark.asyncio
async def test_deep_level_allows_a_third_attempt_and_forces_the_judge_on(monkeypatch):
    # Deliberately the opposite of the global default, to prove "deep" forces
    # the judge on rather than merely respecting settings.DRAFT_JUDGE_ENABLED.
    monkeypatch.setattr(settings, "DRAFT_JUDGE_ENABLED", False)

    graph = create_draft_graph(
        MagicMock(spec=BaseLLMClient), MagicMock(spec=BaseLLMClient)
    )
    state = {**BASE_STATE, "reasoning_level": "deep"}

    with (
        patch.object(WriterAgent, "stream") as mock_writer,
        patch.object(ReviserAgent, "stream") as mock_reviser,
        patch(
            "app.ai.workflows.draft_graph.judge_draft", new_callable=AsyncMock
        ) as mock_judge_draft,
    ):
        mock_writer.side_effect = lambda **kwargs: _one_chunk(BAD_DRAFT)
        mock_reviser.side_effect = lambda **kwargs: _one_chunk(BAD_DRAFT)
        mock_judge_draft.return_value = None

        result = await graph.ainvoke(state)

    # writer (attempt 1) + reviser twice (attempts 2 and 3) = 3 total passes.
    assert mock_writer.call_count == 1
    assert mock_writer.call_args.kwargs["reasoning"] is True
    assert mock_reviser.call_count == 2
    assert mock_judge_draft.call_count == 3
    assert result["attempts"] == 3
    assert result["reasoning_level"] == "deep"


# --- Writer budget -----------------------------------------------------------
#
# `resilience.py` has carried a `writer: 120.0` budget since it was written and
# nothing ever read it -- `draft_graph.py` did not import `node_timeout` at all,
# so the single most expensive step in the ~90s draft budget had no node-level
# protection while appearing in the table as though it did.
#
# The budget is applied inside the node rather than by the decorator on purpose:
# a decorator raises past the node's except clauses and takes the graph down,
# where a timeout has to become a FAILED result the rest of the graph already
# knows how to route.


async def _never_finishes(*_args, **_kwargs):
    """A writer stream that emits one chunk and then hangs."""
    yield "Konu: "
    await asyncio.sleep(3600)


@pytest.mark.asyncio
async def test_a_writer_that_exceeds_its_budget_fails_the_draft_rather_than_the_graph(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.ai.workflows.draft_graph.node_budget", lambda node, level: 0.05
    )
    graph = create_draft_graph(MagicMock(spec=BaseLLMClient))

    with patch.object(WriterAgent, "stream") as mock_writer:
        mock_writer.side_effect = _never_finishes

        result = await graph.ainvoke(BASE_STATE)

    assert result["status"] == "FAILED"
    assert result["requires_human_approval"] is True
    assert result["confidence_score"] == 0.0
    # The partial stream is kept: a truncated draft is more useful to a human
    # than an empty one, and the user already watched it being typed.
    assert result["draft"] == "Konu:"


@pytest.mark.asyncio
async def test_a_writer_timeout_reports_a_readable_reason(monkeypatch):
    """str(TimeoutError()) is empty -- without its own branch the user would
    have been shown "Taslak üretilemedi: " with nothing after the colon."""
    monkeypatch.setattr(
        "app.ai.workflows.draft_graph.node_budget", lambda node, level: 0.05
    )
    graph = create_draft_graph(MagicMock(spec=BaseLLMClient))

    with patch.object(WriterAgent, "stream") as mock_writer:
        mock_writer.side_effect = _never_finishes

        result = await graph.ainvoke(BASE_STATE)

    assert "süre sınırını aştı" in result["error"]
    assert not result["error"].rstrip().endswith(":")


@pytest.mark.asyncio
async def test_the_writer_budget_follows_the_run_s_reasoning_level():
    """`deep` buys wall clock; the writer is where most of it is spent."""
    from app.ai.policy.budget import node_budget

    assert node_budget("writer", ReasoningLevel.DEEP) > node_budget(
        "writer", ReasoningLevel.BALANCED
    )
    assert node_budget("writer", ReasoningLevel.FAST) < node_budget(
        "writer", ReasoningLevel.BALANCED
    )
