"""Tests for the assistant's tool set and its tool-calling loop.

Two things matter structurally here, both load-bearing for the chat/
document_qa merge (see planner.py's module docstring): a document's tools are
closures over the document already attached to *this* request -- the model is
never given a document id to pass as an argument, so it cannot address any
document other than the one attached -- and the tool loop always terminates
in a plain-text answer, whether or not a tool converged.
"""

from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from app.ai.agents.assistant import MAX_TOOL_TURNS, AssistantAgent
from app.ai.llms.base import ToolCallResponse
from app.ai.tools.document_tools import (
    GetDocumentDetailsArgs,
    ToolResult,
    build_assistant_tools,
)
from app.ai.tools.registry import ToolSpec
from app.core.enums.sensitivity_level import SensitivityLevel


def _kwargs(**overrides):
    base = dict(
        document_id=None,
        cached_document={},
        vector_store=None,
        embeddings_client=None,
        qa_sparse_encoder=None,
        qa_result_limit=4,
        rag_graph=None,
        config=None,
    )
    base.update(overrides)
    return base


def test_no_tools_are_built_without_a_document_or_a_legislation_retriever():
    tools = build_assistant_tools(**_kwargs())
    assert tools == []


def test_document_tools_are_built_only_when_a_document_is_attached():
    tools = build_assistant_tools(**_kwargs(document_id="uploads/doc.pdf"))
    names = {tool.name for tool in tools}
    assert names == {
        "search_document",
        "get_document_details",
        "get_document_outline",
        "get_document_section",
    }


def test_legislation_tool_is_available_without_a_document_when_rag_graph_is_configured():
    """A general legal question should not require a document to be attached."""
    tools = build_assistant_tools(**_kwargs(rag_graph=AsyncMock()))
    names = {tool.name for tool in tools}
    assert names == {"search_legislation"}


def test_get_document_details_handler_takes_no_arguments():
    """A model cannot pass a document id through this tool even if it tried --
    the schema has no field for one."""
    assert GetDocumentDetailsArgs.model_fields == {}


@pytest.mark.asyncio
async def test_search_document_handler_is_scoped_to_the_attached_document_id():
    """The handler's own signature has no document-id parameter -- it is
    closed over the one this request attached, structurally preventing the
    model from ever addressing a different document."""
    vector_store = AsyncMock()
    vector_store.hybrid_search.return_value = [{"text": "bulunan parça"}]
    embeddings_client = AsyncMock()
    embeddings_client.embed_query.return_value = [0.1, 0.2]

    class _StubSparseEncoder:
        def encode_query(self, query):
            return [], []

    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/secret.pdf",
            vector_store=vector_store,
            embeddings_client=embeddings_client,
            qa_sparse_encoder=_StubSparseEncoder(),
        )
    )
    search = next(tool for tool in tools if tool.name == "search_document")
    assert list(search.args_schema.model_fields) == ["query"]

    result = await search.handler(query="ne diyor")

    assert result == "bulunan parça"
    call_kwargs = vector_store.hybrid_search.call_args.kwargs
    assert call_kwargs["filter_dict"] == {"storage_path": "uploads/secret.pdf"}


@pytest.mark.asyncio
async def test_search_document_cites_the_hit_page_when_present():
    vector_store = AsyncMock()
    vector_store.hybrid_search.return_value = [
        {"text": "üçüncü sayfadan bir parça", "metadata": {"page": 3}}
    ]
    embeddings_client = AsyncMock()
    embeddings_client.embed_query.return_value = [0.1]

    class _StubSparseEncoder:
        def encode_query(self, query):
            return [], []

    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/doc.pdf",
            vector_store=vector_store,
            embeddings_client=embeddings_client,
            qa_sparse_encoder=_StubSparseEncoder(),
        )
    )
    search = next(tool for tool in tools if tool.name == "search_document")

    result = await search.handler(query="ne diyor")

    assert result == "[s. 3] üçüncü sayfadan bir parça"


@pytest.mark.asyncio
async def test_search_document_falls_back_to_cached_text_when_search_finds_nothing():
    vector_store = AsyncMock()
    vector_store.hybrid_search.return_value = []
    embeddings_client = AsyncMock()
    embeddings_client.embed_query.return_value = [0.1]

    class _StubSparseEncoder:
        def encode_query(self, query):
            return [], []

    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/doc.pdf",
            cached_document={"extracted_text": "belgenin tam metni burada"},
            vector_store=vector_store,
            embeddings_client=embeddings_client,
            qa_sparse_encoder=_StubSparseEncoder(),
        )
    )
    search = next(tool for tool in tools if tool.name == "search_document")

    result = await search.handler(query="herhangi bir soru")

    assert result == "belgenin tam metni burada"


@pytest.mark.asyncio
async def test_get_document_outline_lists_every_page():
    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/doc.pdf",
            cached_document={"pages": ["Sayı: 1\nBirinci sayfa", "İkinci sayfa metni"]},
        )
    )
    outline = next(tool for tool in tools if tool.name == "get_document_outline")

    result = await outline.handler()

    assert "s.1: Sayı: 1" in result
    assert "s.2: İkinci sayfa metni" in result


@pytest.mark.asyncio
async def test_get_document_section_reads_the_requested_page_and_records_the_anchor():
    referenced: list[str] = []
    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/doc.pdf",
            cached_document={"pages": ["birinci sayfa", "ikinci sayfa"]},
            on_anchor_referenced=referenced.append,
        )
    )
    section = next(tool for tool in tools if tool.name == "get_document_section")

    result = await section.handler(page=2)

    assert "ikinci sayfa" in result
    assert result.startswith("[s. 2]")
    assert referenced == ["[s. 2]"]


@pytest.mark.asyncio
async def test_get_document_section_rejects_an_out_of_range_page():
    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/doc.pdf",
            cached_document={"pages": ["tek sayfa"]},
        )
    )
    section = next(tool for tool in tools if tool.name == "get_document_section")

    result = await section.handler(page=5)

    assert "yok" in result


class _NoArgs(BaseModel):
    pass


@pytest.mark.asyncio
async def test_assistant_streams_directly_when_no_tools_are_bound(fake_llm):
    fake_llm.stream_chunks = ["merhaba"]
    agent = AssistantAgent(fake_llm)

    chunks = [
        chunk
        async for chunk in agent.run_stream(
            query="Merhaba", history=[], tools=[]
        )
    ]

    assert "".join(chunks) == "merhaba"
    assert fake_llm.generate_with_tools_calls == []


@pytest.mark.asyncio
async def test_assistant_executes_a_requested_tool_and_streams_the_final_answer(fake_llm):
    handler = AsyncMock(return_value="belgede bulunan cevap")
    tool = ToolSpec(
        name="search_document",
        description="test",
        args_schema=_NoArgs,
        handler=handler,
    )
    fake_llm.generate_with_tools_side_effect = [
        ToolCallResponse(
            content="",
            tool_calls=[{"id": "call-1", "name": "search_document", "args": {"query": "x"}}],
        ),
        ToolCallResponse(content="", tool_calls=[]),
    ]
    fake_llm.stream_chunks = ["işte cevabınız"]
    agent = AssistantAgent(fake_llm)

    chunks = [
        chunk
        async for chunk in agent.run_stream(
            query="Bu belgede ne var?", history=[], tools=[tool]
        )
    ]

    assert "".join(chunks) == "işte cevabınız"
    handler.assert_awaited_once_with(query="x")
    # The tool's result must reach the final generation as context.
    final_messages = fake_llm.stream_calls[-1]["messages"]
    assert any(
        msg.get("role") == "tool" and msg.get("content") == "belgede bulunan cevap"
        for msg in final_messages
    )


@pytest.mark.asyncio
async def test_assistant_stops_after_max_tool_turns_and_still_answers(fake_llm):
    """A model that keeps requesting tools must not loop forever -- after
    MAX_TOOL_TURNS rounds the agent forces a plain-text final answer."""
    handler = AsyncMock(return_value="sonuç")
    tool = ToolSpec(
        name="search_document", description="test", args_schema=_NoArgs, handler=handler
    )
    always_calls_tool = ToolCallResponse(
        content="", tool_calls=[{"id": "x", "name": "search_document", "args": {}}]
    )
    fake_llm.generate_with_tools_side_effect = [always_calls_tool] * MAX_TOOL_TURNS
    fake_llm.stream_chunks = ["nihayetinde cevap"]
    agent = AssistantAgent(fake_llm)

    chunks = [
        chunk async for chunk in agent.run_stream(query="soru", history=[], tools=[tool])
    ]

    assert "".join(chunks) == "nihayetinde cevap"
    assert len(fake_llm.generate_with_tools_calls) == MAX_TOOL_TURNS
    assert handler.await_count == MAX_TOOL_TURNS


# ==========================================
# ToolResult reporting (Faz 2 -- output gate sources)
# ==========================================
@pytest.mark.asyncio
async def test_search_document_reports_a_tool_result_with_the_document_as_source():
    vector_store = AsyncMock()
    vector_store.hybrid_search.return_value = [{"text": "bulunan parça"}]
    embeddings_client = AsyncMock()
    embeddings_client.embed_query.return_value = [0.1]

    class _StubSparseEncoder:
        def encode_query(self, query):
            return [], []

    reported: list[ToolResult] = []
    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/doc.pdf",
            vector_store=vector_store,
            embeddings_client=embeddings_client,
            qa_sparse_encoder=_StubSparseEncoder(),
            on_tool_result=reported.append,
        )
    )
    search = next(tool for tool in tools if tool.name == "search_document")

    await search.handler(query="ne diyor")

    assert len(reported) == 1
    assert reported[0].tool == "search_document"
    assert reported[0].text == "bulunan parça"
    assert reported[0].source_ids == ["uploads/doc.pdf"]
    assert reported[0].confidence == 1.0


@pytest.mark.asyncio
async def test_search_document_fallback_path_reports_lower_confidence():
    vector_store = AsyncMock()
    vector_store.hybrid_search.return_value = []
    embeddings_client = AsyncMock()
    embeddings_client.embed_query.return_value = [0.1]

    class _StubSparseEncoder:
        def encode_query(self, query):
            return [], []

    reported: list[ToolResult] = []
    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/doc.pdf",
            cached_document={"extracted_text": "belgenin tam metni burada"},
            vector_store=vector_store,
            embeddings_client=embeddings_client,
            qa_sparse_encoder=_StubSparseEncoder(),
            on_tool_result=reported.append,
        )
    )
    search = next(tool for tool in tools if tool.name == "search_document")

    await search.handler(query="herhangi bir soru")

    assert reported[0].confidence < 1.0


@pytest.mark.asyncio
async def test_tool_result_carries_the_documents_sensitivity_level():
    """The output gate needs to know a tool result traces back to a
    confidentiality-marked source without re-deriving it itself."""
    reported: list[ToolResult] = []
    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/gizli.pdf",
            cached_document={
                "pages": ["tek sayfa"],
                "analysis": {"guardrail": {"sensitivity_level": "gizli"}},
            },
            on_tool_result=reported.append,
        )
    )
    outline = next(tool for tool in tools if tool.name == "get_document_outline")

    await outline.handler()

    assert reported[0].sensitivity_level is SensitivityLevel.GIZLI


@pytest.mark.asyncio
async def test_get_document_section_reports_its_page_anchor_as_a_citation():
    reported: list[ToolResult] = []
    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/doc.pdf",
            cached_document={"pages": ["birinci sayfa", "ikinci sayfa"]},
            on_tool_result=reported.append,
        )
    )
    section = next(tool for tool in tools if tool.name == "get_document_section")

    await section.handler(page=2)

    assert reported[0].citations == ["[s. 2]"]


@pytest.mark.asyncio
async def test_get_document_section_does_not_report_a_result_for_an_out_of_range_page():
    reported: list[ToolResult] = []
    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/doc.pdf",
            cached_document={"pages": ["tek sayfa"]},
            on_tool_result=reported.append,
        )
    )
    section = next(tool for tool in tools if tool.name == "get_document_section")

    await section.handler(page=5)

    assert reported == []


@pytest.mark.asyncio
async def test_search_legislation_reports_a_tool_result_with_no_document_source():
    rag_graph = AsyncMock()
    rag_graph.ainvoke.return_value = {"context": "ilgili mevzuat metni"}
    reported: list[ToolResult] = []

    tools = build_assistant_tools(**_kwargs(rag_graph=rag_graph, on_tool_result=reported.append))
    search = next(tool for tool in tools if tool.name == "search_legislation")

    await search.handler(query="izin hakkı")

    assert reported[0].tool == "search_legislation"
    assert reported[0].source_ids == []
    assert reported[0].sensitivity_level is SensitivityLevel.UNMARKED


@pytest.mark.asyncio
async def test_search_legislation_reports_nothing_when_no_context_is_found():
    rag_graph = AsyncMock()
    rag_graph.ainvoke.return_value = {"context": ""}
    reported: list[ToolResult] = []

    tools = build_assistant_tools(**_kwargs(rag_graph=rag_graph, on_tool_result=reported.append))
    search = next(tool for tool in tools if tool.name == "search_legislation")

    await search.handler(query="alakasız")

    assert reported == []


@pytest.mark.asyncio
async def test_an_unknown_tool_name_does_not_crash_the_loop(fake_llm):
    fake_llm.generate_with_tools_side_effect = [
        ToolCallResponse(content="", tool_calls=[{"id": "1", "name": "ghost_tool", "args": {}}]),
        ToolCallResponse(content="", tool_calls=[]),
    ]
    fake_llm.stream_chunks = ["yine de cevap verdim"]
    tool = ToolSpec(
        name="search_document", description="test", args_schema=_NoArgs, handler=AsyncMock()
    )
    agent = AssistantAgent(fake_llm)

    chunks = [
        chunk async for chunk in agent.run_stream(query="soru", history=[], tools=[tool])
    ]

    assert "".join(chunks) == "yine de cevap verdim"
