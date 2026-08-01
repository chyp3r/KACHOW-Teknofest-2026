"""Integration-style tests for the draft graph's reflexion loop.

The former single-pass "writer -> LLM editor" pipeline had no path back to the
writer, so a low-scoring draft was only ever flagged, never repaired. These
tests exercise the actual compiled graph (writer/reviser streaming is mocked,
everything else -- routing, the deterministic verifier, state accumulation --
runs for real) to prove the loop only fires when a defect is text-revisable,
stops at MAX_DRAFT_ATTEMPTS, and short-circuits to a human question when the
writer leaves an explicit placeholder instead.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.ai.agents.reviser import ReviserAgent
from app.ai.agents.writer import WriterAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.draft_graph import MAX_DRAFT_ATTEMPTS, create_draft_graph
from app.core.config import settings

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
