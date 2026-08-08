"""Unit tests for ExampleRetriever: the draft writer's few-shot example lookup."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document

from app.ai.retrieval.examples import ExampleRetriever
from app.ai.retrieval.hybrid import HybridRetriever


def _doc(text: str, *, correspondence_type: str, kurum: str, niyet: str = "", baslik: str = "") -> Document:
    return Document(
        page_content=text,
        metadata={
            "correspondence_type": correspondence_type,
            "kurum": kurum,
            "niyet": niyet,
            "baslik": baslik,
        },
    )


def _retriever(documents: list[Document]) -> ExampleRetriever:
    hybrid = MagicMock(spec=HybridRetriever)
    hybrid.retrieve = AsyncMock(return_value=documents)
    return ExampleRetriever(hybrid), hybrid


@pytest.mark.asyncio
async def test_correspondence_type_is_forwarded_as_a_hard_filter():
    retriever, hybrid = _retriever([])

    await retriever.retrieve(query="bilgi talebi", correspondence_type="response_letter", limit=2)

    _, kwargs = hybrid.retrieve.call_args
    assert kwargs["filter_dict"] == {"correspondence_type": "response_letter"}


@pytest.mark.asyncio
async def test_two_examples_from_the_same_kurum_keep_only_the_first():
    documents = [
        _doc("A metni", correspondence_type="response_letter", kurum="Bursa Belediyesi"),
        _doc("B metni", correspondence_type="response_letter", kurum="Bursa Belediyesi"),
        _doc("C metni", correspondence_type="response_letter", kurum="İzmir Belediyesi"),
    ]
    retriever, _ = _retriever(documents)

    examples = await retriever.retrieve(
        query="talep", correspondence_type="response_letter", limit=2
    )

    assert [example.kurum for example in examples] == ["Bursa Belediyesi", "İzmir Belediyesi"]


@pytest.mark.asyncio
async def test_result_is_capped_at_the_requested_limit():
    documents = [
        _doc(f"metin {i}", correspondence_type="response_letter", kurum=f"Kurum {i}")
        for i in range(6)
    ]
    retriever, _ = _retriever(documents)

    examples = await retriever.retrieve(
        query="talep", correspondence_type="response_letter", limit=2
    )

    assert len(examples) == 2


@pytest.mark.asyncio
async def test_char_budget_drops_the_longest_example_first():
    documents = [
        _doc("x" * 100, correspondence_type="response_letter", kurum="Kurum A"),
        _doc("y" * 3000, correspondence_type="response_letter", kurum="Kurum B"),
    ]
    retriever, _ = _retriever(documents)

    examples = await retriever.retrieve(
        query="talep", correspondence_type="response_letter", limit=2, char_budget=1000
    )

    assert [example.kurum for example in examples] == ["Kurum A"]


@pytest.mark.asyncio
async def test_char_budget_never_drops_below_one_example():
    documents = [_doc("z" * 9000, correspondence_type="response_letter", kurum="Kurum A")]
    retriever, _ = _retriever(documents)

    examples = await retriever.retrieve(
        query="talep", correspondence_type="response_letter", limit=2, char_budget=1000
    )

    assert len(examples) == 1


@pytest.mark.asyncio
async def test_empty_query_returns_empty_without_calling_the_retriever():
    retriever, hybrid = _retriever([])

    examples = await retriever.retrieve(
        query="   ", correspondence_type="response_letter", limit=2
    )

    assert examples == []
    hybrid.retrieve.assert_not_called()


@pytest.mark.asyncio
async def test_missing_correspondence_type_returns_empty_without_calling_the_retriever():
    retriever, hybrid = _retriever([])

    examples = await retriever.retrieve(query="talep", correspondence_type="", limit=2)

    assert examples == []
    hybrid.retrieve.assert_not_called()


@pytest.mark.asyncio
async def test_a_retriever_failure_degrades_to_an_empty_list():
    hybrid = MagicMock(spec=HybridRetriever)
    hybrid.retrieve = AsyncMock(side_effect=RuntimeError("qdrant unreachable"))
    retriever = ExampleRetriever(hybrid)

    examples = await retriever.retrieve(
        query="talep", correspondence_type="response_letter", limit=2
    )

    assert examples == []
