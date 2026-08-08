"""Tests for the draft graph's few-shot style-example retrieval.

Exercises the actual compiled graph (writer/reviser streaming mocked, the
retrieve_examples node runs for real against a mocked ExampleRetriever) to
prove: retrieval is optional (None retriever, a disabled policy, or a
retrieval failure all degrade to zero examples rather than failing the
draft), the retrieved examples reach both the writer and reviser prompts
with the "style reference only" boundary block, and revise_node does not
re-query -- the repair pass sees the same examples as the original draft.
"""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.agents.reviser import ReviserAgent
from app.ai.agents.writer import WriterAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.policy import get_policy
from app.ai.retrieval.examples import ExampleRetriever, StyleExample
from app.ai.workflows.draft_graph import create_draft_graph
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
}

STYLE_EXAMPLE = StyleExample(
    text="T.C. ÖRNEK BAKANLIĞI\nKonu: Örnek\n\nArz ederim.",
    correspondence_type="cover_letter",
    niyet="ek_belge_iletimi",
    kurum="Örnek Bakanlığı",
    baslik="Örnek Yazı",
)


async def _one_chunk(text: str):
    yield text


def _mock_llm_client() -> MagicMock:
    client = MagicMock(spec=BaseLLMClient)
    client.count_tokens = MagicMock(return_value=1)
    return client


def _mock_example_retriever(examples: list[StyleExample]) -> MagicMock:
    retriever = MagicMock(spec=ExampleRetriever)
    retriever.retrieve = AsyncMock(return_value=examples)
    return retriever


@pytest.fixture(autouse=True)
def _disable_judge(monkeypatch):
    monkeypatch.setattr(settings, "DRAFT_JUDGE_ENABLED", False)


@pytest.mark.asyncio
async def test_no_retriever_configured_yields_no_examples_and_no_prompt_section():
    graph = create_draft_graph(_mock_llm_client(), example_retriever=None)

    with patch.object(WriterAgent, "stream") as mock_writer:
        mock_writer.side_effect = lambda **kwargs: _one_chunk(GOOD_DRAFT)
        result = await graph.ainvoke(BASE_STATE)

    assert result["style_examples"] == []
    prompt = mock_writer.call_args.kwargs["messages"]
    assert "ÜSLUP REFERANS ÖRNEKLERİ" not in prompt


@pytest.mark.asyncio
async def test_retrieved_examples_are_injected_into_the_writer_prompt_with_the_boundary_rule():
    retriever = _mock_example_retriever([STYLE_EXAMPLE])
    graph = create_draft_graph(_mock_llm_client(), example_retriever=retriever)

    with patch.object(WriterAgent, "stream") as mock_writer:
        mock_writer.side_effect = lambda **kwargs: _one_chunk(GOOD_DRAFT)
        result = await graph.ainvoke(BASE_STATE)

    assert [example["kurum"] for example in result["style_examples"]] == ["Örnek Bakanlığı"]
    prompt = mock_writer.call_args.kwargs["messages"]
    assert "ÜSLUP REFERANS ÖRNEKLERİ" in prompt
    assert STYLE_EXAMPLE.text in prompt
    assert "TAŞIMA" in prompt  # the "style only, not a fact source" rule


@pytest.mark.asyncio
async def test_the_revise_pass_reuses_the_same_examples_without_re_querying():
    retriever = _mock_example_retriever([STYLE_EXAMPLE])
    graph = create_draft_graph(_mock_llm_client(), example_retriever=retriever)

    with (
        patch.object(WriterAgent, "stream") as mock_writer,
        patch.object(ReviserAgent, "stream") as mock_reviser,
    ):
        mock_writer.side_effect = lambda **kwargs: _one_chunk(BAD_DRAFT)
        mock_reviser.side_effect = lambda **kwargs: _one_chunk(GOOD_DRAFT)
        result = await graph.ainvoke(BASE_STATE)

    assert retriever.retrieve.call_count == 1
    reviser_prompt = mock_reviser.call_args.kwargs["messages"]
    assert "ÜSLUP REFERANS ÖRNEKLERİ" in reviser_prompt
    assert result["style_examples"]


@pytest.mark.asyncio
async def test_a_retrieval_failure_degrades_to_zero_examples_not_a_failed_draft():
    retriever = MagicMock(spec=ExampleRetriever)
    retriever.retrieve = AsyncMock(side_effect=RuntimeError("qdrant unreachable"))
    graph = create_draft_graph(_mock_llm_client(), example_retriever=retriever)

    with patch.object(WriterAgent, "stream") as mock_writer:
        mock_writer.side_effect = lambda **kwargs: _one_chunk(GOOD_DRAFT)
        result = await graph.ainvoke(BASE_STATE)

    assert result["style_examples"] == []
    assert result["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_the_policy_switch_disables_retrieval_without_touching_the_retriever():
    retriever = _mock_example_retriever([STYLE_EXAMPLE])
    disabled = replace(get_policy(), draft=replace(get_policy().draft, style_examples_enabled=False))

    graph = create_draft_graph(_mock_llm_client(), example_retriever=retriever)

    with (
        patch("app.ai.workflows.draft_graph.get_policy", return_value=disabled),
        patch.object(WriterAgent, "stream") as mock_writer,
    ):
        mock_writer.side_effect = lambda **kwargs: _one_chunk(GOOD_DRAFT)
        result = await graph.ainvoke(BASE_STATE)

    retriever.retrieve.assert_not_called()
    assert result["style_examples"] == []
