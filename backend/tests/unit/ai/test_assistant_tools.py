"""Tests for the assistant's tool set and its tool-calling loop.

Two things matter structurally here, both load-bearing for the chat/
document_qa merge (see planner.py's module docstring): a document's tools are
closures over the document already attached to *this* request -- the model is
never given a document id to pass as an argument, so it cannot address any
document other than the one attached -- and the tool loop always terminates
in a plain-text answer, whether or not a tool converged.
"""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from app.ai.agents.assistant import (
    MAX_TOOL_TURNS_EVREN,
    MAX_TOOL_TURNS_LOCAL,
    AssistantAgent,
    _GIVEUP_RETRY_NUDGE,
    _NARRATION_NUDGE,
    _NO_RETRIEVAL_NUDGE,
    _final_answer_nudge,
    _looks_like_giveup,
    _looks_like_narration,
    _max_tool_turns,
)
from app.ai.llms.base import ToolCallResponse
from app.ai.tools.document_tools import (
    GetDocumentDetailsArgs,
    ToolResult,
    WEAK_SCORE_THRESHOLD,
    build_assistant_tools,
)
from app.ai.tools.registry import ToolSpec
from app.core.enums.sensitivity_level import SensitivityLevel
from app.mcp.manager import mcp_manager
from app.mcp.registry import MEVZUAT_SERVER


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
        "search_document_regex",
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


# ==========================================
# search_document_regex (RAG dışı, birebir/regex satır araması)
# ==========================================
_DEFAULT_REGEX_DOC = {"pages": ["Sayı: E-12345\nGövde", "İkinci sayfa: 15/08/2024"]}


def _regex_tools(reported=None, cached_document=None):
    return build_assistant_tools(
        **_kwargs(
            document_id="uploads/doc.pdf",
            cached_document=cached_document or _DEFAULT_REGEX_DOC,
            on_tool_result=(reported.append if reported is not None else None),
        )
    )


@pytest.mark.asyncio
async def test_search_document_regex_finds_a_literal_string_with_page_anchor():
    tool = next(t for t in _regex_tools() if t.name == "search_document_regex")

    result = await tool.handler(pattern="E-12345")

    assert "[s. 1] Sayı: E-12345" in result


@pytest.mark.asyncio
async def test_search_document_regex_supports_actual_regex_syntax():
    tool = next(t for t in _regex_tools() if t.name == "search_document_regex")

    result = await tool.handler(pattern=r"\d{2}/\d{2}/\d{4}")

    assert "[s. 2]" in result
    assert "15/08/2024" in result


@pytest.mark.asyncio
async def test_search_document_regex_reports_no_match_without_crashing():
    tool = next(t for t in _regex_tools() if t.name == "search_document_regex")

    result = await tool.handler(pattern="bulunmayan-dizge")

    assert "eşleşen satır bulunamadı" in result


@pytest.mark.asyncio
async def test_search_document_regex_rejects_an_invalid_pattern():
    tool = next(t for t in _regex_tools() if t.name == "search_document_regex")

    result = await tool.handler(pattern="([unclosed")

    assert result.startswith("Geçersiz düzenli ifade")


@pytest.mark.asyncio
async def test_search_document_regex_reports_a_tool_result_with_the_document_as_source():
    reported: list[ToolResult] = []
    tool = next(t for t in _regex_tools(reported) if t.name == "search_document_regex")

    await tool.handler(pattern="Sayı")

    assert len(reported) == 1
    assert reported[0].tool == "search_document_regex"
    assert reported[0].source_ids == ["uploads/doc.pdf"]


@pytest.mark.asyncio
async def test_search_document_regex_truncates_and_notes_the_total():
    pages = ["\n".join(f"satır {i} numara" for i in range(120))]
    tool = next(
        t
        for t in _regex_tools(cached_document={"pages": pages})
        if t.name == "search_document_regex"
    )

    result = await tool.handler(pattern="numara")

    assert "toplam 120 eşleşmenin ilk 40" in result


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
async def test_assistant_reuses_the_tool_loops_own_final_answer_without_restreaming(fake_llm):
    """When generate_with_tools' last turn already wrote the answer (no more
    tool calls, non-empty content), run_stream must reuse it instead of
    paying for a second, redundant generation through stream() -- that
    second pass is what pushed the "assist" node's 70s budget (node_budget in
    app/ai/policy/schema.py) past its limit on a real multi-tool-turn
    request: two generate_with_tools calls plus stream() again for content
    the model had already produced."""
    handler = AsyncMock(return_value="belgede bulunan cevap")
    tool = ToolSpec(
        name="search_document", description="test", args_schema=_NoArgs, handler=handler
    )
    fake_llm.generate_with_tools_side_effect = [
        ToolCallResponse(
            content="",
            tool_calls=[{"id": "call-1", "name": "search_document", "args": {"query": "x"}}],
        ),
        ToolCallResponse(content="gerçek cevap burada", tool_calls=[]),
    ]
    # Deliberately distinct from the expected answer -- if run_stream falls
    # through to stream() anyway, the assertion below fails loudly instead of
    # coincidentally matching.
    fake_llm.stream_chunks = ["BU YANIT KULLANILMAMALI"]
    agent = AssistantAgent(fake_llm)

    chunks = [
        chunk
        async for chunk in agent.run_stream(
            query="Bu belgede ne var?", history=[], tools=[tool]
        )
    ]

    assert "".join(chunks) == "gerçek cevap burada"
    assert fake_llm.stream_calls == []


@pytest.mark.asyncio
async def test_assistant_stops_after_max_tool_turns_and_still_answers(fake_llm):
    """A model that keeps requesting tools must not loop forever -- after
    the provider's tool-turn cap the agent forces a plain-text final answer."""
    max_turns = _max_tool_turns()
    handler = AsyncMock(return_value="sonuç")
    tool = ToolSpec(
        name="search_document", description="test", args_schema=_NoArgs, handler=handler
    )
    always_calls_tool = ToolCallResponse(
        content="", tool_calls=[{"id": "x", "name": "search_document", "args": {}}]
    )
    fake_llm.generate_with_tools_side_effect = [always_calls_tool] * max_turns
    fake_llm.stream_chunks = ["nihayetinde cevap"]
    agent = AssistantAgent(fake_llm)

    chunks = [
        chunk async for chunk in agent.run_stream(query="soru", history=[], tools=[tool])
    ]

    assert "".join(chunks) == "nihayetinde cevap"
    assert len(fake_llm.generate_with_tools_calls) == max_turns
    assert handler.await_count == max_turns


@pytest.mark.asyncio
async def test_tool_turn_cap_follows_provider(fake_llm):
    """Local (Ollama) mode keeps the tight 2-turn cap; connected to Evren the
    agent gets the wider 5-turn cap so it can try several tools before it
    converges on an answer."""
    handler = AsyncMock(return_value="sonuç")
    tool = ToolSpec(
        name="search_document", description="test", args_schema=_NoArgs, handler=handler
    )
    always_calls_tool = ToolCallResponse(
        content="", tool_calls=[{"id": "x", "name": "search_document", "args": {}}]
    )

    for local_mode, expected in ((True, MAX_TOOL_TURNS_LOCAL), (False, MAX_TOOL_TURNS_EVREN)):
        handler.reset_mock()
        fake_llm.generate_with_tools_calls.clear()
        fake_llm.generate_with_tools_side_effect = [always_calls_tool] * (expected + 2)
        fake_llm.stream_chunks = ["cevap"]
        agent = AssistantAgent(fake_llm)

        with patch("app.ai.agents.assistant.settings.LOCAL_MODE", local_mode):
            _ = [
                chunk
                async for chunk in agent.run_stream(
                    query="soru", history=[], tools=[tool]
                )
            ]

        assert len(fake_llm.generate_with_tools_calls) == expected
        assert handler.await_count == expected


# ==========================================
# "Bulamadım" için erken pes etme koruması
# ==========================================
@pytest.mark.parametrize(
    "text",
    [
        "Yüklü evrakta bu bilgiye ulaşamadım.",
        "Belgede böyle bir ifade geçmiyor.",
        "Bu konuda bir bilgi bulamadım.",
        "İlgili tarih belgede belirtilmemiş.",
        "Evrakta bu isimden söz edilmemektedir.",
    ],
)
def test_looks_like_giveup_matches_common_phrasings(text):
    assert _looks_like_giveup(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Evrak 12.03.2026 tarihli olup konu yıllık izin talebidir.",
        "Belgede 657 sayılı Kanun'a atıf yapılmıştır.",
        "",
        None,
    ],
)
def test_looks_like_giveup_leaves_real_answers_alone(text):
    assert _looks_like_giveup(text) is False


@pytest.mark.parametrize(
    "text",
    [
        # The exact reported regression.
        "Şimdi de \"Hacettepe\" kelimesiyle birlikte \"R&D\" veya \"Community\" "
        "gibi kelimeleri içeren tüm geçişleri kontrol edelim:",
        "Bir de şu terimleri arayalım.",
        "Önce belgenin sayfa dökümüne bakalım.",
        "Şimdi ilgili bölümü inceleyelim:",
        "Bir sonraki adımda tam metni okuyacağım.",
    ],
)
def test_looks_like_narration_catches_an_announced_next_step(text):
    assert _looks_like_narration(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Evrak, 15 günlük yıllık izin talebidir [s. 2].",
        "Belgede ACM ICPC'ye dair bir bilgi bulunmamaktadır.",
        "Merhaba, size nasıl yardımcı olabilirim?",
        "",
        None,
    ],
)
def test_looks_like_narration_leaves_real_answers_alone(text):
    assert _looks_like_narration(text) is False


def test_an_announced_next_step_is_rejected_even_after_searching():
    """The reported breakage: the model replied with a search plan instead of
    an answer, and because it carried no tool call the loop shipped it to the
    user as the final reply. Rejected regardless of how many searches ran."""
    assert (
        _final_answer_nudge(
            content='Şimdi de "Hacettepe" ile "R&D" geçişlerini kontrol edelim:',
            require_retrieval=True,
            has_tools=True,
            tool_calls_made=3,
            max_tool_turns=5,
        )
        == _NARRATION_NUDGE
    )


def test_a_confident_answer_written_without_any_search_is_rejected():
    """The reported bug: the model answers about the document having called
    nothing at all. It reads as a real answer, so the give-up pattern never
    matches -- the only signal is the zero tool-call count."""
    assert (
        _final_answer_nudge(
            content="Evrak, 15 günlük yıllık izin talebidir.",
            require_retrieval=True,
            has_tools=True,
            tool_calls_made=0,
            max_tool_turns=5,
        )
        == _NO_RETRIEVAL_NUDGE
    )


def test_a_giveup_after_one_search_still_gets_the_giveup_nudge():
    assert (
        _final_answer_nudge(
            content="Bu bilgiye ulaşamadım.",
            require_retrieval=True,
            has_tools=True,
            tool_calls_made=1,
            max_tool_turns=5,
        )
        == _GIVEUP_RETRY_NUDGE
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        # Small talk / no document -- nothing to search, never second-guess.
        dict(require_retrieval=False, has_tools=True, tool_calls_made=0, max_tool_turns=5),
        # Nothing bound to call.
        dict(require_retrieval=True, has_tools=False, tool_calls_made=0, max_tool_turns=5),
        # Searched, and the answer is a real answer.
        dict(require_retrieval=True, has_tools=True, tool_calls_made=2, max_tool_turns=5),
    ],
)
def test_final_answer_nudge_accepts_legitimate_answers(kwargs):
    assert _final_answer_nudge(content="Evrak bir izin talebidir.", **kwargs) is None


def test_a_giveup_once_the_budget_is_spent_is_accepted():
    """Every allowed tool call was made -- 'couldn't find it' is genuine now."""
    assert (
        _final_answer_nudge(
            content="Bu bilgiye ulaşamadım.",
            require_retrieval=True,
            has_tools=True,
            tool_calls_made=5,
            max_tool_turns=5,
        )
        is None
    )


@pytest.mark.asyncio
async def test_an_answer_with_zero_searches_is_not_accepted_and_the_model_is_nudged(fake_llm):
    """End-to-end: a document-attached turn whose first reply is a confident
    answer with no tool call at all must not reach the user -- the loop pushes
    the model back to its tools and only then accepts."""
    handler = AsyncMock(return_value="[s. 3] ... on beş gün ...")
    tool = ToolSpec(
        name="search_document", description="test", args_schema=_NoArgs, handler=handler
    )
    fake_llm.generate_with_tools_side_effect = [
        # Straight to an answer, nothing called -- the reported bug.
        ToolCallResponse(content="Evrak 10 günlük izin talebidir.", tool_calls=[]),
        ToolCallResponse(
            content="",
            tool_calls=[{"id": "c1", "name": "search_document", "args": {"query": "izin"}}],
        ),
        ToolCallResponse(content="Belgede 15 gün olarak belirtilmiş.", tool_calls=[]),
    ]
    agent = AssistantAgent(fake_llm)

    chunks = [
        chunk
        async for chunk in agent.run_stream(
            query="Kaç gün izin isteniyor?",
            history=[],
            tools=[tool],
            require_retrieval=True,
        )
    ]

    # The un-searched answer never reached the user.
    assert "".join(chunks) == "Belgede 15 gün olarak belirtilmiş."
    assert "10 günlük" not in "".join(chunks)
    assert handler.await_count == 1
    last_messages = fake_llm.generate_with_tools_calls[-1]["messages"]
    assert any(
        msg.get("role") == "user" and msg.get("content") == _NO_RETRIEVAL_NUDGE
        for msg in last_messages
    )
    # The rejected text must not survive in context -- keeping it let the
    # hallucinated answer bleed back into the final reply.
    assert not any("10 günlük" in (msg.get("content") or "") for msg in last_messages)


@pytest.mark.asyncio
async def test_a_search_plan_never_reaches_the_user_as_the_final_answer(fake_llm):
    """End-to-end for the reported breakage: after being nudged the model
    answered with a plan ('şimdi de ... kontrol edelim:') and no tool call.
    That text must be rejected, not streamed to the user as the reply."""
    handler = AsyncMock(return_value="[s. 1] ACM Hacettepe -- TEKNOFEST Teams Lead")
    tool = ToolSpec(
        name="search_document_regex", description="test", args_schema=_NoArgs, handler=handler
    )
    fake_llm.generate_with_tools_side_effect = [
        ToolCallResponse(
            content="",
            tool_calls=[{"id": "c1", "name": "search_document_regex", "args": {"pattern": "ICPC"}}],
        ),
        ToolCallResponse(
            content='Şimdi de "Hacettepe" ile "R&D" geçişlerini kontrol edelim:',
            tool_calls=[],
        ),
        ToolCallResponse(
            content="Belgede ACM Hacettepe'de TEKNOFEST Teams Lead görevi kayıtlıdır [s. 1].",
            tool_calls=[],
        ),
    ]
    agent = AssistantAgent(fake_llm)

    chunks = [
        chunk
        async for chunk in agent.run_stream(
            query="ICPC madalyası var mı?",
            history=[],
            tools=[tool],
            require_retrieval=True,
        )
    ]

    answer = "".join(chunks)
    assert answer == "Belgede ACM Hacettepe'de TEKNOFEST Teams Lead görevi kayıtlıdır [s. 1]."
    assert "kontrol edelim" not in answer
    last_messages = fake_llm.generate_with_tools_calls[-1]["messages"]
    assert any(
        msg.get("role") == "user" and msg.get("content") == _NARRATION_NUDGE
        for msg in last_messages
    )


@pytest.mark.asyncio
async def test_a_giveup_reply_with_a_document_is_not_accepted_and_the_model_is_nudged(fake_llm):
    """Belge ekliyken, model erişim bütçesini tüketmeden 'bulamadım' diyerek
    turu bitirmeye çalışırsa yanıt kabul edilmez; bir düzeltme mesajıyla
    yeniden denemesi istenir."""
    handler = AsyncMock(return_value="3. sayfada geçiyor")
    tool = ToolSpec(
        name="search_document", description="test", args_schema=_NoArgs, handler=handler
    )
    fake_llm.generate_with_tools_side_effect = [
        ToolCallResponse(
            content="",
            tool_calls=[{"id": "c0", "name": "search_document", "args": {"query": "a"}}],
        ),
        ToolCallResponse(content="Bu bilgiye ulaşamadım.", tool_calls=[]),
        ToolCallResponse(
            content="",
            tool_calls=[{"id": "c1", "name": "search_document", "args": {"query": "b"}}],
        ),
        ToolCallResponse(content="Belgede 15 gün olarak belirtilmiş.", tool_calls=[]),
    ]
    agent = AssistantAgent(fake_llm)

    chunks = [
        chunk
        async for chunk in agent.run_stream(
            query="Kaç gün izin isteniyor?",
            history=[],
            tools=[tool],
            require_retrieval=True,
        )
    ]

    assert "".join(chunks) == "Belgede 15 gün olarak belirtilmiş."
    assert handler.await_count == 2
    # The corrective nudge reached the model as a user message.
    last_messages = fake_llm.generate_with_tools_calls[-1]["messages"]
    assert any(
        msg.get("role") == "user" and msg.get("content") == _GIVEUP_RETRY_NUDGE
        for msg in last_messages
    )


@pytest.mark.asyncio
async def test_a_giveup_reply_without_a_document_is_accepted_immediately(fake_llm):
    """require_retrieval=False -- an out-of-scope 'I can't help with that'
    must not be second-guessed."""
    tool = ToolSpec(
        name="search_document", description="test", args_schema=_NoArgs,
        handler=AsyncMock(return_value="x"),
    )
    fake_llm.generate_with_tools_side_effect = [
        ToolCallResponse(content="Bu konuda bilgi bulamadım.", tool_calls=[]),
    ]
    agent = AssistantAgent(fake_llm)

    chunks = [
        chunk
        async for chunk in agent.run_stream(
            query="hava nasıl?", history=[], tools=[tool], require_retrieval=False
        )
    ]

    assert "".join(chunks) == "Bu konuda bilgi bulamadım."
    assert len(fake_llm.generate_with_tools_calls) == 1


@pytest.mark.asyncio
async def test_no_nudge_ever_sends_a_system_turn_mid_conversation(fake_llm):
    """Regression: the nudges were first injected with role="system", which
    Evren's vLLM rejects outright --

        400 ... "System message must be at the beginning"

    -- failing the whole turn with "Yanıt üretilemedi". It also violated
    BaseAgent._prepare_messages' own contract (exactly one system turn, at
    index 0, owned by the agent). Every provider call this loop makes must
    carry a system message only as its first message."""
    handler = AsyncMock(return_value="sonuç")
    tool = ToolSpec(
        name="search_document", description="test", args_schema=_NoArgs, handler=handler
    )
    # Drive every nudge branch in one run: a bare answer with no search, then
    # a search plan, then a premature give-up.
    fake_llm.generate_with_tools_side_effect = [
        ToolCallResponse(content="Evrak bir izin talebidir.", tool_calls=[]),
        ToolCallResponse(
            content="",
            tool_calls=[{"id": "c1", "name": "search_document", "args": {}}],
        ),
        ToolCallResponse(content="Şimdi de diğer sayfalara bakalım:", tool_calls=[]),
        ToolCallResponse(content="Bu bilgiye ulaşamadım.", tool_calls=[]),
        ToolCallResponse(content="Belgede 15 gün yazıyor [s. 2].", tool_calls=[]),
    ]
    fake_llm.stream_chunks = ["yedek"]
    agent = AssistantAgent(fake_llm)

    _ = [
        chunk
        async for chunk in agent.run_stream(
            query="soru", history=[], tools=[tool], require_retrieval=True
        )
    ]

    sent = fake_llm.generate_with_tools_calls + fake_llm.stream_calls
    assert len(sent) > 1, "expected the nudge branches to actually run"
    for call in sent:
        roles = [msg.get("role") for msg in call["messages"]]
        assert roles[0] == "system"
        assert "system" not in roles[1:], f"mid-conversation system turn: {roles}"


@pytest.mark.asyncio
async def test_a_stubborn_model_still_terminates(fake_llm):
    """A model that keeps answering with no tool call must not loop forever --
    the nudge budget is capped, so the turn still ends."""
    tool = ToolSpec(
        name="search_document", description="test", args_schema=_NoArgs,
        handler=AsyncMock(return_value="x"),
    )
    fake_llm.generate_with_tools_side_effect = [
        ToolCallResponse(content="Evrak bir izin talebidir.", tool_calls=[])
    ] * (_max_tool_turns() + 3)
    fake_llm.stream_chunks = ["yedek cevap"]
    agent = AssistantAgent(fake_llm)

    chunks = [
        chunk
        async for chunk in agent.run_stream(
            query="soru", history=[], tools=[tool], require_retrieval=True
        )
    ]

    assert "".join(chunks)
    assert len(fake_llm.generate_with_tools_calls) <= _max_tool_turns()


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


# ==========================================
# Dinamik mevzuat-mcp eskalasyonu (chat) -- LOCAL_MODE
# ==========================================
#: Bir belgeye karşılık gelen Qdrant Document nesnesi taklidi -- yalnızca
#: guard'ın okuduğu tek alanı (`metadata["score"]`) taşır.
class _FakeDoc:
    def __init__(self, score: float):
        self.metadata = {"score": score}


def _live_registered():
    """Canlı aracın göründüğü üç şart: LOCAL_MODE kapalı, MEVZUAT_MCP_ENABLED
    açık, sunucu gerçekten kayıtlı -- ikisi de build_live_legislation_tools()'un
    gerektirdiği şey (bkz. test_registry.py'nin aynı desenli `_enabled()`'ı)."""
    mcp_manager.clients[MEVZUAT_SERVER] = object()
    return patch.multiple(
        "app.core.config.settings", LOCAL_MODE=False, MEVZUAT_MCP_ENABLED=True
    )


@pytest.fixture(autouse=True)
def _clean_mcp_registry():
    mcp_manager.clients.clear()
    yield
    mcp_manager.clients.clear()


def test_live_legislation_tool_absent_when_local_mode_is_true():
    """LOCAL_MODE açıkken canlı araç hiç görünmemeli -- diğer iki şart
    (MEVZUAT_MCP_ENABLED, kayıt) tutsa bile. mevzuat-mcp bu modda yalnızca
    boot'taki curated 7 kanunu çekmek için kullanılır, istek başına değil."""
    mcp_manager.clients[MEVZUAT_SERVER] = object()
    with patch.multiple(
        "app.core.config.settings", LOCAL_MODE=True, MEVZUAT_MCP_ENABLED=True
    ):
        tools = build_assistant_tools(**_kwargs(rag_graph=AsyncMock()))
    names = {tool.name for tool in tools}
    assert "search_legislation_live" not in names


def test_live_legislation_tool_absent_when_global_flag_is_off():
    """LOCAL_MODE=false tek başına yetmez -- MEVZUAT_MCP_ENABLED kapalıyken
    build_live_legislation_tools() zaten boş liste döner."""
    mcp_manager.clients[MEVZUAT_SERVER] = object()
    with patch.multiple(
        "app.core.config.settings", LOCAL_MODE=False, MEVZUAT_MCP_ENABLED=False
    ):
        tools = build_assistant_tools(**_kwargs(rag_graph=AsyncMock()))
    names = {tool.name for tool in tools}
    assert "search_legislation_live" not in names


def test_live_legislation_tool_present_when_local_mode_false_and_global_switch_on():
    with _live_registered():
        tools = build_assistant_tools(**_kwargs(rag_graph=AsyncMock()))
    names = {tool.name for tool in tools}
    assert "search_legislation_live" in names


@pytest.mark.asyncio
async def test_live_search_declines_without_hitting_mcp_when_called_before_local():
    """Model, search_legislation'ı hiç denemeden search_legislation_live'ı
    çağırırsa (ya da aynı yanıtta ikisini birden isteyip live'ı önce
    işletirse), guard ağa hiç çıkmamalı."""
    rag_graph = AsyncMock()
    rag_graph.ainvoke.return_value = {"context": "", "documents": []}

    with _live_registered(), patch(
        "app.ai.tools.mevzuat_tools._lookup", new_callable=AsyncMock
    ) as lookup:
        tools = build_assistant_tools(**_kwargs(rag_graph=rag_graph))
        live = next(tool for tool in tools if tool.name == "search_legislation_live")

        result = await live.handler(query="657")

        lookup.assert_not_called()
    assert "search_legislation" in result


@pytest.mark.asyncio
async def test_live_search_declines_when_local_result_is_strong():
    rag_graph = AsyncMock()
    rag_graph.ainvoke.return_value = {
        "context": "ilgili mevzuat metni",
        "documents": [_FakeDoc(score=WEAK_SCORE_THRESHOLD + 1.0)],
    }

    with _live_registered(), patch(
        "app.ai.tools.mevzuat_tools._lookup", new_callable=AsyncMock
    ) as lookup:
        tools = build_assistant_tools(**_kwargs(rag_graph=rag_graph))
        search = next(tool for tool in tools if tool.name == "search_legislation")
        live = next(tool for tool in tools if tool.name == "search_legislation_live")

        await search.handler(query="izin hakkı")
        await live.handler(query="izin hakkı")

        lookup.assert_not_called()


@pytest.mark.asyncio
async def test_live_search_escalates_when_local_result_is_weak_and_reports_a_tool_result():
    """Bu, aynı zamanda gerçek keşifte bulunan groundedness hatasının
    regresyon testi: search_legislation_live'ın canlı sonucu, on_tool_result
    aracılığıyla raporlanmalı -- yoksa output_gate'in dayanaklılık kontrolü
    onu hiç göremez ve içindeki her somut iddiayı karartır."""
    rag_graph = AsyncMock()
    rag_graph.ainvoke.return_value = {
        "context": "zayıf eşleşme",
        "documents": [_FakeDoc(score=0.0)],
    }
    reported: list[ToolResult] = []

    with _live_registered(), patch(
        "app.ai.tools.mevzuat_tools._lookup", new_callable=AsyncMock
    ) as lookup:
        lookup.return_value = "(Kaynak: mevzuat.gov.tr, mevzuat_id=102924)\n\nMadde 1..."
        tools = build_assistant_tools(
            **_kwargs(rag_graph=rag_graph, on_tool_result=reported.append)
        )
        search = next(tool for tool in tools if tool.name == "search_legislation")
        live = next(tool for tool in tools if tool.name == "search_legislation_live")

        await search.handler(query="657")
        result = await live.handler(query="657")

        lookup.assert_called_once()

    assert "mevzuat_id=102924" in result
    live_results = [r for r in reported if r.tool == "search_legislation_live"]
    assert len(live_results) == 1
    assert live_results[0].sensitivity_level is SensitivityLevel.UNMARKED


@pytest.mark.asyncio
async def test_live_search_escalates_when_local_returns_no_documents_at_all():
    rag_graph = AsyncMock()
    rag_graph.ainvoke.return_value = {"context": "", "documents": []}

    with _live_registered(), patch(
        "app.ai.tools.mevzuat_tools._lookup", new_callable=AsyncMock
    ) as lookup:
        lookup.return_value = "(Kaynak: mevzuat.gov.tr, mevzuat_id=1)\n\nMetin"
        tools = build_assistant_tools(**_kwargs(rag_graph=rag_graph))
        search = next(tool for tool in tools if tool.name == "search_legislation")
        live = next(tool for tool in tools if tool.name == "search_legislation_live")

        await search.handler(query="olmayan bir mevzuat")
        await live.handler(query="olmayan bir mevzuat")

        lookup.assert_called_once()


@pytest.mark.asyncio
async def test_live_search_not_found_result_is_not_reported_as_a_tool_result():
    """mevzuat_tools.NOT_FOUND, gerçek bir bulgu değildir -- diğer her
    başarısız handler gibi (bkz. test_search_legislation_reports_nothing_
    when_no_context_is_found), rapor edilmemeli."""
    from app.ai.tools.mevzuat_tools import NOT_FOUND

    rag_graph = AsyncMock()
    rag_graph.ainvoke.return_value = {"context": "", "documents": []}
    reported: list[ToolResult] = []

    with _live_registered(), patch(
        "app.ai.tools.mevzuat_tools._lookup", new_callable=AsyncMock
    ) as lookup:
        lookup.return_value = NOT_FOUND
        tools = build_assistant_tools(
            **_kwargs(rag_graph=rag_graph, on_tool_result=reported.append)
        )
        search = next(tool for tool in tools if tool.name == "search_legislation")
        live = next(tool for tool in tools if tool.name == "search_legislation_live")

        await search.handler(query="bulunamayacak")
        await live.handler(query="bulunamayacak")

    assert reported == []
