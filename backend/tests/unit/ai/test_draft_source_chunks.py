"""Tests for the draft graph's source-document chunk retrieval (Faz F).

Exercises the actual compiled graph (writer streaming mocked, the
retrieve_source_chunks node runs for real against a mocked HybridRetriever)
to prove: retrieval is optional (no retriever, no document_id, a disabled
policy, or a retrieval failure all degrade to zero chunks rather than
failing the draft), and retrieved chunks are appended to the brief that
reaches the writer as verbatim excerpts, not folded into the summary.
"""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from app.ai.agents.writer import WriterAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.policy import get_policy
from app.ai.retrieval.hybrid import HybridRetriever
from app.ai.workflows.draft_graph import create_draft_graph
from app.core.config import settings

SOURCE_DOCUMENT = "Sayı: E-1-1, Tarih: 30.07.2026 tarihli evrak."

GOOD_DRAFT = (
    "Konu: Test Konusu\n"
    "Sayı: E-1-1\n"
    "Tarih: 30.07.2026\n\n"
    "Sayın Makam,\n\n"
    "Arz ederim.\n\n"
    "Ali Veli\nGenel Müdür"
)

BASE_STATE = {
    "source_document": SOURCE_DOCUMENT,
    "classification": {
        "document_type_label": "Resmî Yazı",
        "summary": "Test evrakı.",
        "fields": {"konu": "Test konusu"},
        "missing_fields": [],
    },
    "correspondence_type": "cover_letter",
    "context": "İlgili mevzuat metni burada.",
    "instructions": "Test talimatı.",
    "user_request": "Bu evraka cevap yazısı hazırla.",
    "document_id": "doc-1",
}

CHUNK = Document(
    page_content="Madde 5: Başvurular 30 gün içinde yanıtlanır.",
    metadata={"page": 3},
)


async def _one_chunk(text: str):
    yield text


def _mock_llm_client() -> MagicMock:
    client = MagicMock(spec=BaseLLMClient)
    client.count_tokens = MagicMock(return_value=1)
    return client


def _mock_document_qa_retriever(documents: list[Document]) -> MagicMock:
    retriever = MagicMock(spec=HybridRetriever)
    retriever.retrieve = AsyncMock(return_value=documents)
    return retriever


@pytest.fixture(autouse=True)
def _disable_judge(monkeypatch):
    monkeypatch.setattr(settings, "DRAFT_JUDGE_ENABLED", False)


@pytest.mark.asyncio
async def test_no_retriever_configured_yields_no_chunks_and_no_prompt_section():
    graph = create_draft_graph(_mock_llm_client(), document_qa_retriever=None)

    with patch.object(WriterAgent, "stream") as mock_writer:
        mock_writer.side_effect = lambda **kwargs: _one_chunk(GOOD_DRAFT)
        result = await graph.ainvoke(BASE_STATE)

    assert result["source_chunks"] == []
    prompt = mock_writer.call_args.kwargs["messages"]
    assert "BELGEDEN İLGİLİ ALINTILAR" not in prompt


@pytest.mark.asyncio
async def test_no_document_id_skips_retrieval_even_with_a_retriever_configured():
    retriever = _mock_document_qa_retriever([CHUNK])
    graph = create_draft_graph(_mock_llm_client(), document_qa_retriever=retriever)
    state = {**BASE_STATE, "document_id": ""}

    with patch.object(WriterAgent, "stream") as mock_writer:
        mock_writer.side_effect = lambda **kwargs: _one_chunk(GOOD_DRAFT)
        result = await graph.ainvoke(state)

    retriever.retrieve.assert_not_called()
    assert result["source_chunks"] == []


@pytest.mark.asyncio
async def test_retrieved_chunks_are_injected_into_the_writer_prompt_as_verbatim_excerpts():
    retriever = _mock_document_qa_retriever([CHUNK])
    graph = create_draft_graph(_mock_llm_client(), document_qa_retriever=retriever)

    with patch.object(WriterAgent, "stream") as mock_writer:
        mock_writer.side_effect = lambda **kwargs: _one_chunk(GOOD_DRAFT)
        result = await graph.ainvoke(BASE_STATE)

    assert len(result["source_chunks"]) == 1
    retriever.retrieve.assert_called_once()
    _, kwargs = retriever.retrieve.call_args
    assert kwargs["filter_dict"] == {"storage_path": "doc-1"}

    prompt = mock_writer.call_args.kwargs["messages"]
    assert "BELGEDEN İLGİLİ ALINTILAR" in prompt
    assert CHUNK.page_content in prompt
    assert "(sayfa 3)" in prompt
    # The summary section (2) stays intact -- chunks are additive, not a replacement.
    assert "Test evrakı." in prompt


@pytest.mark.asyncio
async def test_a_retrieval_failure_degrades_to_zero_chunks_not_a_failed_draft():
    retriever = MagicMock(spec=HybridRetriever)
    retriever.retrieve = AsyncMock(side_effect=RuntimeError("qdrant unreachable"))
    graph = create_draft_graph(_mock_llm_client(), document_qa_retriever=retriever)

    with patch.object(WriterAgent, "stream") as mock_writer:
        mock_writer.side_effect = lambda **kwargs: _one_chunk(GOOD_DRAFT)
        result = await graph.ainvoke(BASE_STATE)

    assert result["source_chunks"] == []
    assert result["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_the_policy_switch_disables_retrieval_without_touching_the_retriever():
    retriever = _mock_document_qa_retriever([CHUNK])
    disabled = replace(get_policy(), draft=replace(get_policy().draft, source_chunks_enabled=False))

    graph = create_draft_graph(_mock_llm_client(), document_qa_retriever=retriever)

    with (
        patch("app.ai.workflows.draft_graph.get_policy", return_value=disabled),
        patch.object(WriterAgent, "stream") as mock_writer,
    ):
        mock_writer.side_effect = lambda **kwargs: _one_chunk(GOOD_DRAFT)
        result = await graph.ainvoke(BASE_STATE)

    retriever.retrieve.assert_not_called()
    assert result["source_chunks"] == []


@pytest.mark.asyncio
async def test_chunks_beyond_the_char_budget_are_dropped_but_at_least_one_survives():
    huge_first = Document(page_content="A" * 100, metadata={})
    second = Document(page_content="B" * 100, metadata={})
    retriever = _mock_document_qa_retriever([huge_first, second])
    tight_budget = replace(
        get_policy(), draft=replace(get_policy().draft, source_chunk_char_budget=50)
    )

    graph = create_draft_graph(_mock_llm_client(), document_qa_retriever=retriever)

    with (
        patch("app.ai.workflows.draft_graph.get_policy", return_value=tight_budget),
        patch.object(WriterAgent, "stream") as mock_writer,
    ):
        mock_writer.side_effect = lambda **kwargs: _one_chunk(GOOD_DRAFT)
        result = await graph.ainvoke(BASE_STATE)

    # The first chunk always survives even though it alone exceeds the
    # budget (a budget of zero chunks would defeat the point of grounding);
    # the second is dropped since the budget is already spent.
    assert len(result["source_chunks"]) == 1
    assert result["source_chunks"][0]["text"] == huge_first.page_content
