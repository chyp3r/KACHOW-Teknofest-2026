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


# ==========================================
# get_document_details / missing_fields shape (regression)
# ==========================================
_ANALYSIS_WITH_MISSING_FIELDS = {
    "pages": ["tek sayfa"],
    "extracted_text": "tek sayfa",
    "analysis": {
        "summary": "İzin talebi",
        "compliance_status": "eksik_bilgi",
        # Every real producer (document_analysis_graph.py's check_compliance_node)
        # writes MissingField.model_dump() dicts here, never bare strings -- this
        # is the actual on-disk shape, not a simplified test fixture.
        "missing_fields": [
            {
                "key": "sayi",
                "label": "Sayı",
                "severity": "zorunlu",
                "mevzuat": "RYUEHY m.11",
                "reason": "Belgelerde sayı bulunması zorunludur.",
            },
            {
                "key": "muhatap",
                "label": "Muhatap",
                "severity": "zorunlu",
                "mevzuat": "RYUEHY m.14",
                "reason": "Muhatap belirtilmelidir.",
            },
        ],
    },
}


@pytest.mark.asyncio
async def test_get_document_details_does_not_crash_on_a_document_with_missing_fields():
    """18 of 20 real cached analyses have a non-empty missing_fields at this
    exact shape. `", ".join(list_of_dicts)` raised TypeError on every one of
    them, and the assistant swallowed it -- answering without the document's
    analysis, silently, no error surfaced to the user."""
    tools = build_assistant_tools(
        **_kwargs(document_id="uploads/evrak.pdf", cached_document=_ANALYSIS_WITH_MISSING_FIELDS)
    )
    details = next(tool for tool in tools if tool.name == "get_document_details")

    text = await details.handler()

    assert "İzin talebi" in text
    assert "Sayı" in text
    assert "Muhatap" in text


@pytest.mark.asyncio
async def test_get_document_details_tolerates_string_missing_fields_too():
    """Defensive: if some future producer ever writes plain strings instead of
    MissingField dicts, this must still render rather than crash."""
    doc = {
        "pages": ["x"],
        "extracted_text": "x",
        "analysis": {"summary": "özet", "missing_fields": ["Sayı", "Muhatap"]},
    }
    tools = build_assistant_tools(**_kwargs(document_id="uploads/evrak.pdf", cached_document=doc))
    details = next(tool for tool in tools if tool.name == "get_document_details")

    text = await details.handler()

    assert "Sayı" in text and "Muhatap" in text


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
    """The fallback text must carry a visible marker, not just an internal
    `confidence` value the model itself never sees. Before this, a retrieval
    outage and 'genuinely no matching passage' both silently returned the
    document's opening lines with no distinguishing signal at all, so a
    question about page 40 of a 60-page document got answered -- wrongly,
    with unwarranted confidence -- from pages 1-2."""
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

    assert "belgenin tam metni burada" in result
    assert "[Not:" in result


@pytest.mark.asyncio
async def test_search_document_carries_the_degraded_marker_into_the_reported_result_too():
    """The side-channel ToolResult.text (what output_gate's groundedness check
    reads) must be the exact same string the model saw, marker included --
    not a second, silently different copy."""
    vector_store = AsyncMock()
    vector_store.hybrid_search.return_value = []
    embeddings_client = AsyncMock()
    embeddings_client.embed_query.return_value = [0.1]

    class _StubSparseEncoder:
        def encode_query(self, query):
            return [], []

    reported = []
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

    result = await search.handler(query="herhangi bir soru")

    assert reported[0].text == result
    assert reported[0].confidence == 0.5


@pytest.mark.asyncio
async def test_search_document_does_not_mark_a_real_targeted_hit_as_degraded():
    """The marker must only appear on the fallback path -- a genuine search
    hit is exactly as confident as it always was."""
    vector_store = AsyncMock()
    vector_store.hybrid_search.return_value = [{"text": "hedefli sonuç", "metadata": {}}]
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

    assert result == "hedefli sonuç"
    assert "[Not:" not in result


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


# ==========================================
# Deny-at-retrieval clearance gating (Faz 4 -- RBAC)
# ==========================================
_GIZLI_DOC = {
    "pages": ["tek sayfa"],
    "extracted_text": "tek sayfa",
    "analysis": {"summary": "özet", "guardrail": {"sensitivity_level": "gizli"}},
}


@pytest.mark.asyncio
async def test_document_tools_refuse_when_clearance_is_insufficient():
    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/gizli.pdf",
            cached_document=_GIZLI_DOC,
            requester_clearance=SensitivityLevel.OZEL,
        )
    )
    outline = next(tool for tool in tools if tool.name == "get_document_outline")
    details = next(tool for tool in tools if tool.name == "get_document_details")
    section = next(tool for tool in tools if tool.name == "get_document_section")

    assert "yeterli yetkiniz yok" in await outline.handler()
    assert "yeterli yetkiniz yok" in await details.handler()
    assert "yeterli yetkiniz yok" in await section.handler(page=1)


@pytest.mark.asyncio
async def test_search_document_refuses_when_clearance_is_insufficient():
    vector_store = AsyncMock()
    embeddings_client = AsyncMock()
    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/gizli.pdf",
            cached_document=_GIZLI_DOC,
            vector_store=vector_store,
            embeddings_client=embeddings_client,
            requester_clearance=SensitivityLevel.OZEL,
        )
    )
    search = next(tool for tool in tools if tool.name == "search_document")

    result = await search.handler(query="ne diyor")

    assert "yeterli yetkiniz yok" in result
    # Never even reaches Qdrant -- deny-at-retrieval, not filter-and-hope.
    vector_store.hybrid_search.assert_not_called()


@pytest.mark.asyncio
async def test_document_tools_proceed_when_clearance_is_sufficient():
    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/gizli.pdf",
            cached_document=_GIZLI_DOC,
            requester_clearance=SensitivityLevel.COK_GIZLI,
        )
    )
    outline = next(tool for tool in tools if tool.name == "get_document_outline")

    result = await outline.handler()

    assert "yeterli yetkiniz yok" not in result


@pytest.mark.asyncio
async def test_document_tools_proceed_on_exact_clearance_match():
    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/gizli.pdf",
            cached_document=_GIZLI_DOC,
            requester_clearance=SensitivityLevel.GIZLI,
        )
    )
    outline = next(tool for tool in tools if tool.name == "get_document_outline")

    result = await outline.handler()

    assert "yeterli yetkiniz yok" not in result


@pytest.mark.asyncio
async def test_document_tools_skip_the_check_when_clearance_is_unknown():
    """requester_clearance=None means REQUIRE_AUTH is off -- the documented
    fully-open local-dev escape hatch, same convention the ownership check
    already uses. Must not silently refuse every document interaction."""
    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/gizli.pdf",
            cached_document=_GIZLI_DOC,
            requester_clearance=None,
        )
    )
    outline = next(tool for tool in tools if tool.name == "get_document_outline")

    result = await outline.handler()

    assert "yeterli yetkiniz yok" not in result


@pytest.mark.asyncio
async def test_search_document_includes_the_clearance_rank_in_the_qdrant_filter():
    vector_store = AsyncMock()
    vector_store.hybrid_search.return_value = [{"text": "bulunan parça"}]
    embeddings_client = AsyncMock()
    embeddings_client.embed_query.return_value = [0.1]

    class _StubSparseEncoder:
        def encode_query(self, query):
            return [], []

    tools = build_assistant_tools(
        **_kwargs(
            document_id="uploads/unmarked.pdf",
            vector_store=vector_store,
            embeddings_client=embeddings_client,
            qa_sparse_encoder=_StubSparseEncoder(),
            requester_clearance=SensitivityLevel.OZEL,
        )
    )
    search = next(tool for tool in tools if tool.name == "search_document")

    await search.handler(query="ne diyor")

    call_kwargs = vector_store.hybrid_search.call_args.kwargs
    assert call_kwargs["filter_dict"] == {
        "storage_path": "uploads/unmarked.pdf",
        "sensitivity_rank": {"lte": SensitivityLevel.OZEL.rank},
    }


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
