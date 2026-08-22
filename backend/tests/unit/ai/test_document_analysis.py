"""Unit tests for the incoming-document (evrak) analysis workflow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from app.ai.compliance import EvrakField
from app.ai.guardrails.llm_nuance import GuardrailJudgeVerdict
from app.ai.llms.base import BaseLLMClient
from app.ai.retrieval.hybrid import HybridRetriever
from app.ai.workflows.document_analysis_graph import (
    ANALYSIS_MAX_TOKENS,
    DocumentAnalysisOutput,
    DocumentClassificationOutput,
    MevzuatSuggestion,
    MevzuatSuggestionOutput,
    _build_mevzuat_query,
    _trim_for_extraction,
    create_document_analysis_graph,
)
from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.document_type import DocumentType

OFFICIAL_LETTER_TEXT = (
    "T.C.\nÖRNEK BAKANLIĞI\nSayı: E-123-456\nTarih: 30.07.2026\n"
    "Konu: Yıllık İzin Talebi\nİLGİLİ MAKAMA\nMehmet Öztürk\nGenel Müdür"
)

# Deliberately missing the "Sayı:" heading and any addressee line, so the
# deterministic parser cannot rescue those two fields.
INCOMPLETE_LETTER_TEXT = (
    "T.C.\nÖRNEK BAKANLIĞI\nTarih: 30.07.2026\n"
    "Konu: Yıllık İzin Talebi\n\nMetin arz ederim.\n\nMehmet Öztürk\nGenel Müdür"
)

COMPLETE_FIELDS = EvrakField(
    sayi="E-123-456",
    tarih="30.07.2026",
    konu="Yıllık İzin Talebi",
    muhatap="İLGİLİ MAKAMA",
    gonderen_kurum="Örnek Bakanlığı",
    imza_sahibi="Mehmet Öztürk",
    imza_unvani="Genel Müdür",
)


def _merged(document_type: DocumentType, summary: str, **field_overrides) -> DocumentAnalysisOutput:
    """Build the single merged classify+extract return value the analyze node expects."""
    fields = EvrakField(**field_overrides).model_dump()
    return DocumentAnalysisOutput(document_type=document_type, summary=summary, **fields)


# ==========================================
# Pure helpers
# ==========================================
def test_trim_keeps_short_documents_untouched():
    assert _trim_for_extraction("kısa metin") == "kısa metin"


def test_trim_preserves_head_and_tail_of_long_documents():
    """Header fields live at the start and the imza block at the end."""
    text = "BASLIK" + ("x" * 20000) + "IMZA"
    trimmed = _trim_for_extraction(text)

    assert trimmed.startswith("BASLIK")
    assert trimmed.endswith("IMZA")
    assert "kısaltıldı" in trimmed
    assert len(trimmed) < len(text)


def test_mevzuat_query_is_built_deterministically_from_labels():
    """BM25 matches literal tokens, so the type label and konu drive the query
    plus the vocabulary of the legislation governing that type."""
    state = {
        "document_type": DocumentType.OFFICIAL_LETTER.value,
        "document_type_label": "Resmî Yazı",
        "fields": {"konu": "Personel Eğitimi"},
    }
    query = _build_mevzuat_query(state)

    assert "Resmî Yazı" in query
    assert "Personel Eğitimi" in query
    assert "resmî yazışma" in query
    assert _build_mevzuat_query(state) == query


def test_mevzuat_query_terms_follow_the_document_type():
    """One fixed suffix was correct when the corpus held a single realistic
    target. Against seven laws it biased every query toward the correspondence
    regulation and pulled leave requests away from the law that governs them."""
    leave = _build_mevzuat_query(
        {
            "document_type": DocumentType.LEAVE_REQUEST.value,
            "document_type_label": "İzin Talebi",
        }
    )
    letter = _build_mevzuat_query(
        {
            "document_type": DocumentType.OFFICIAL_LETTER.value,
            "document_type_label": "Resmî Yazı",
        }
    )

    assert "izin" in leave
    assert "resmî yazışma" not in leave
    assert "resmî yazışma" in letter


def test_mevzuat_query_falls_back_on_an_unknown_document_type():
    query = _build_mevzuat_query({"document_type": "uydurma", "document_type_label": "X"})
    assert query.strip()


def test_mevzuat_query_tolerates_empty_state():
    query = _build_mevzuat_query({})
    assert query.startswith("resmî yazı")
    assert "sayı" in query


# ==========================================
# Graph without a retriever
# ==========================================
@pytest.mark.asyncio
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_detects_missing_fields_without_retriever(mock_classify):
    mock_classify.return_value = _merged(
        DocumentType.OFFICIAL_LETTER, "İzin talebi yazısı.", muhatap="Belirtilmemiş"
    )

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": INCOMPLETE_LETTER_TEXT})

    assert result["document_type"] == DocumentType.OFFICIAL_LETTER.value
    assert result["document_type_label"] == "Resmî Yazı"
    assert result["summary"] == "İzin talebi yazısı."
    assert result["compliance_status"] == ComplianceStatus.INCOMPLETE.value
    # "Belirtilmemiş" counts as absent, not as a value. `tarih` is NOT reported
    # missing: the deterministic parser reads it straight off the document even
    # though the model returned nothing at all.
    assert {item["key"] for item in result["missing_fields"]} == {"muhatap", "sayi"}
    assert result["fields"]["tarih"] == "30.07.2026"
    assert result["missing_fields"][0]["mevzuat"]
    assert result["mevzuat_documents"] == []
    assert result["mevzuat_suggestions"] == []


@pytest.mark.asyncio
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_reports_compliant_document(mock_classify):
    mock_classify.return_value = _merged(
        DocumentType.OFFICIAL_LETTER, "Tam evrak.", **COMPLETE_FIELDS.model_dump()
    )

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert result["compliance_status"] == ComplianceStatus.COMPLIANT.value
    assert result["missing_fields"] == []


@pytest.mark.asyncio
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_flags_a_typed_name_with_no_detected_signature(mock_classify):
    """End-to-end: detected_marks threaded through the graph's initial state
    (see DocumentAnalysisState's own comment on why this isn't a separate
    node/branch) reaches check_compliance_node and produces the advisory
    "İmza görseli" finding -- the gap a typed imza_sahibi name alone hides."""
    mock_classify.return_value = _merged(
        DocumentType.OFFICIAL_LETTER, "Tam evrak.", **COMPLETE_FIELDS.model_dump()
    )

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke(
        {
            "input_text": OFFICIAL_LETTER_TEXT,
            "detected_marks": [{"kind": "stamp", "page": 1, "bbox": (0, 0, 10, 10), "confidence": 0.6}],
        }
    )

    assert result["compliance_status"] == ComplianceStatus.PARTIALLY_COMPLIANT.value
    assert [item["key"] for item in result["missing_fields"]] == ["imza_gorseli"]


@pytest.mark.asyncio
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_reports_no_signature_gap_when_a_signature_mark_is_present(mock_classify):
    mock_classify.return_value = _merged(
        DocumentType.OFFICIAL_LETTER, "Tam evrak.", **COMPLETE_FIELDS.model_dump()
    )

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke(
        {
            "input_text": OFFICIAL_LETTER_TEXT,
            "detected_marks": [{"kind": "signature", "page": 1, "bbox": (0, 0, 10, 10), "confidence": 0.6}],
        }
    )

    assert result["compliance_status"] == ComplianceStatus.COMPLIANT.value
    assert result["missing_fields"] == []


@pytest.mark.asyncio
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_without_detected_marks_key_does_not_flag_the_signature_gap(mock_classify):
    """detected_marks entirely absent from the initial state (e.g. a
    born-digital PDF, or the planning_graph.py cached-document re-invocation
    that never threads it) must read as unknown, not unsigned."""
    mock_classify.return_value = _merged(
        DocumentType.OFFICIAL_LETTER, "Tam evrak.", **COMPLETE_FIELDS.model_dump()
    )

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert result["compliance_status"] == ComplianceStatus.COMPLIANT.value
    assert result["missing_fields"] == []


@pytest.mark.asyncio
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_passes_analysis_call_parameters(mock_classify):
    """Run-to-run reproducibility requires temperature 0, not the 0.7 default."""
    mock_classify.return_value = _merged(DocumentType.PETITION, "Dilekçe.")

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    await graph.ainvoke({"input_text": "dilekçe metni"})

    assert mock_classify.call_args.kwargs["temperature"] == 0.0
    assert mock_classify.call_args.kwargs["max_tokens"] == ANALYSIS_MAX_TOKENS


@pytest.mark.asyncio
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_adds_ocr_warning_to_prompts(mock_classify):
    mock_classify.return_value = _merged(DocumentType.OTHER, "x")

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    await graph.ainvoke({"input_text": "taranmış metin", "is_ocr_text": True})

    assert "OCR" in mock_classify.call_args.kwargs["messages"]


# ==========================================
# Graph with a retriever
# ==========================================
@pytest.mark.asyncio
@patch("app.ai.agents.compliance.ComplianceAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_suggests_mevzuat_from_retrieved_excerpts(mock_classify, mock_suggest):
    # The incomplete fixture has no "Sayı:" heading, so neither the parser nor the
    # model supplies it and it genuinely reaches the missing-field list.
    mock_classify.return_value = _merged(
        DocumentType.OFFICIAL_LETTER,
        "İzin talebi.",
        **COMPLETE_FIELDS.model_copy(update={"sayi": None}).model_dump(),
    )
    mock_suggest.return_value = MevzuatSuggestionOutput(
        suggestions=[
            MevzuatSuggestion(
                mevzuat="Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik m.11",
                aciklama="Belgelerde sayı bulunması zorunludur.",
            )
        ]
    )

    retriever = AsyncMock(spec=HybridRetriever)
    retriever.retrieve.return_value = [
        Document(
            page_content="MADDE 11- Belgelerde sayı bulunması zorunludur.",
            # Must resolve to the same law (2646) the suggestion cites --
            # "RYUEHY" hits the alias table the same way the real corpus's
            # full title hits LAW_TITLES, see citation_support/test_mevzuat_citation.py.
            metadata={"mevzuat": "RYUEHY"},
        )
    ]

    graph = create_document_analysis_graph(
        MagicMock(spec=BaseLLMClient), mevzuat_retriever=retriever
    )
    result = await graph.ainvoke({"input_text": INCOMPLETE_LETTER_TEXT})

    assert len(result["mevzuat_suggestions"]) == 1
    assert "m.11" in result["mevzuat_suggestions"][0]["mevzuat"]
    # The query is built deterministically and must reach the retriever
    # carrying literal mandatory-element vocabulary ("sayı" among it).
    assert "sayı" in retriever.retrieve.call_args.args[0]


@pytest.mark.asyncio
@patch("app.ai.agents.compliance.ComplianceAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_drops_a_fabricated_citation_and_falls_back_to_raw_citation(
    mock_classify, mock_suggest
):
    """The prompt asks the model not to invent a madde/kanun absent from the
    excerpts; this is the check that actually enforces it. A suggestion
    citing law 3071, when the only retrieved excerpt is RYUEHY, must never
    reach the API response -- it is replaced by the grounded-by-construction
    raw citation for the excerpt that *was* actually retrieved."""
    mock_classify.return_value = _merged(
        DocumentType.OFFICIAL_LETTER,
        "İzin talebi.",
        **COMPLETE_FIELDS.model_copy(update={"sayi": None}).model_dump(),
    )
    mock_suggest.return_value = MevzuatSuggestionOutput(
        suggestions=[
            MevzuatSuggestion(
                mevzuat="3071 sayılı Dilekçe Hakkının Kullanılmasına Dair Kanun m.4",
                aciklama="Dilekçede imza bulunması gerekir.",
            )
        ]
    )

    retriever = AsyncMock(spec=HybridRetriever)
    retriever.retrieve.return_value = [
        Document(page_content="MADDE 11- Belgelerde sayı bulunması zorunludur.", metadata={"mevzuat": "RYUEHY"})
    ]

    graph = create_document_analysis_graph(
        MagicMock(spec=BaseLLMClient), mevzuat_retriever=retriever
    )
    result = await graph.ainvoke({"input_text": INCOMPLETE_LETTER_TEXT})

    assert result["mevzuat_suggestions"] == [
        {
            "mevzuat": "RYUEHY",
            "aciklama": "İlgili olabilecek mevzuat alıntısı (otomatik açıklama üretilemedi).",
        }
    ]


@pytest.mark.asyncio
@patch("app.ai.agents.compliance.ComplianceAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_keeps_a_grounded_citation_but_replaces_an_ungrounded_explanation(
    mock_classify, mock_suggest
):
    """The citation is real (law 2646, article 11 is genuinely in the
    excerpt) but the explanation invents an institution the document never
    mentions. Only the explanation should be swapped for the neutral
    fallback text -- the citation itself is what requirement 5 needs and
    must survive untouched."""
    mock_classify.return_value = _merged(
        DocumentType.OFFICIAL_LETTER,
        "İzin talebi.",
        **COMPLETE_FIELDS.model_copy(update={"sayi": None}).model_dump(),
    )
    mock_suggest.return_value = MevzuatSuggestionOutput(
        suggestions=[
            MevzuatSuggestion(
                mevzuat="RYUEHY m.11",
                aciklama=(
                    "Bu husus Enerji ve Tabii Kaynaklar Bakanlığı Hukuk Müşavirliği "
                    "tarafından da teyit edilmiştir."
                ),
            )
        ]
    )

    retriever = AsyncMock(spec=HybridRetriever)
    retriever.retrieve.return_value = [
        Document(page_content="MADDE 11- Belgelerde sayı bulunması zorunludur.", metadata={"mevzuat": "RYUEHY"})
    ]

    graph = create_document_analysis_graph(
        MagicMock(spec=BaseLLMClient), mevzuat_retriever=retriever
    )
    result = await graph.ainvoke({"input_text": INCOMPLETE_LETTER_TEXT})

    assert len(result["mevzuat_suggestions"]) == 1
    assert result["mevzuat_suggestions"][0]["mevzuat"] == "RYUEHY m.11"
    assert result["mevzuat_suggestions"][0]["aciklama"] == (
        "İlgili olabilecek mevzuat alıntısı (otomatik açıklama üretilemedi)."
    )


@pytest.mark.asyncio
@patch("app.ai.agents.compliance.ComplianceAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_keeps_an_empty_suggestion_list_empty_rather_than_backfilling(
    mock_classify, mock_suggest
):
    """A model that looked at the excerpts and genuinely found nothing worth
    suggesting must stay empty -- the raw-citation fallback exists for a
    failed or fabricated answer, not to override a legitimate empty one."""
    mock_classify.return_value = _merged(
        DocumentType.OFFICIAL_LETTER, "x", **COMPLETE_FIELDS.model_dump()
    )
    mock_suggest.return_value = MevzuatSuggestionOutput(suggestions=[])

    retriever = AsyncMock(spec=HybridRetriever)
    retriever.retrieve.return_value = [
        Document(page_content="MADDE 11-", metadata={"mevzuat": "RYUEHY"})
    ]

    graph = create_document_analysis_graph(
        MagicMock(spec=BaseLLMClient), mevzuat_retriever=retriever
    )
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert result["mevzuat_suggestions"] == []


@pytest.mark.asyncio
@patch("app.ai.agents.compliance.ComplianceAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_missing_fields_is_identical_regardless_of_the_mevzuat_source(
    mock_classify, mock_suggest
):
    """PR3's whole premise: MEVZUAT_SOURCE picks where retrieve_mevzuat reads
    citations from, and must never touch check_compliance. check_compliance
    and retrieve_mevzuat run as independent parallel branches over disjoint
    state keys (see create_document_analysis_graph's own docstring) -- this
    locks that architectural separation in from the outside, rather than
    trusting it holds just because the code isn't wired the other way today.
    Two retrievers standing in for "local" and "mcp" return deliberately
    different excerpts (a local-only retriever would legitimately do that,
    an MCP outage would too) -- missing_fields must not move a byte either
    way, only mevzuat_references may differ."""
    mock_classify.return_value = _merged(
        DocumentType.OFFICIAL_LETTER,
        "İzin talebi.",
        **COMPLETE_FIELDS.model_copy(update={"sayi": None}).model_dump(),
    )
    mock_suggest.return_value = MevzuatSuggestionOutput(suggestions=[])

    local_retriever = AsyncMock(spec=HybridRetriever)
    local_retriever.retrieve.return_value = [
        Document(page_content="MADDE 11- yerel korpus.", metadata={"mevzuat": "Yerel"})
    ]
    mcp_retriever = AsyncMock()
    mcp_retriever.retrieve.return_value = [
        Document(page_content="MADDE 11- canlı mevzuat.", metadata={"mevzuat": "MCP"})
    ]

    local_graph = create_document_analysis_graph(
        MagicMock(spec=BaseLLMClient), mevzuat_retriever=local_retriever
    )
    mcp_graph = create_document_analysis_graph(
        MagicMock(spec=BaseLLMClient), mevzuat_retriever=mcp_retriever
    )

    local_result = await local_graph.ainvoke({"input_text": INCOMPLETE_LETTER_TEXT})
    mcp_result = await mcp_graph.ainvoke({"input_text": INCOMPLETE_LETTER_TEXT})

    assert local_result["missing_fields"] == mcp_result["missing_fields"]
    assert local_result["compliance_status"] == mcp_result["compliance_status"]
    assert local_result["missing_fields"], "fixture must actually exercise a non-empty case"
    # The retrieval branch, in contrast, is exactly where they're allowed to differ.
    assert local_result["mevzuat_documents"] != mcp_result["mevzuat_documents"]


@pytest.mark.asyncio
@patch("app.ai.workflows.document_analysis_graph.node_budget")
@patch("app.ai.agents.compliance.ComplianceAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_inner_budgets_read_reasoning_level_from_state_explicitly(
    mock_classify, mock_suggest, mock_node_budget
):
    """suggest_mevzuat_node's inner asyncio.wait_for bound and its outer
    @node_timeout decorator must resolve a budget for the same node from the
    same state, or a fast run makes the inner bound (0.85x) exceed the outer
    node_timeout and the degradation path below becomes unreachable. Before
    the fix, the inner call site was `node_budget("suggest_mevzuat")` -- the
    level argument omitted outright rather than read from state -- so the
    two call sites agreed only by coincidence. DocumentAnalysisState carries
    no reasoning_level field yet: LangGraph builds its channels from the
    state schema and drops any input key the schema doesn't declare, so
    state.get("reasoning_level") reads None today regardless of what
    ainvoke() is given. What this locks in is that the call site explicitly
    performs that lookup and passes it through -- two positional args, not
    one -- so the day the field is added, it stays coupled by construction
    instead of by luck.

    Detailed summarization used to follow this exact inner-budget-share
    pattern too (a second node_budget("summarize", ...) call site), but it
    is no longer a graph node at all -- see create_document_analysis_graph's
    own docstring for why -- so only suggest_mevzuat_node remains, the only
    node that calls `node_budget` directly from
    document_analysis_graph.py's own function bodies. @node_timeout's own
    internal node_budget call lives in resilience.py, a different import
    binding, and is not intercepted by this patch (see that decorator's own
    module).
    """
    mock_classify.return_value = _merged(
        DocumentType.OFFICIAL_LETTER, "x", **COMPLETE_FIELDS.model_dump()
    )
    mock_suggest.return_value = MevzuatSuggestionOutput(suggestions=[])
    mock_node_budget.return_value = 42.0

    retriever = AsyncMock(spec=HybridRetriever)
    retriever.retrieve.return_value = [
        Document(page_content="MADDE 11-", metadata={"mevzuat": "RYUEHY"})
    ]

    graph = create_document_analysis_graph(
        MagicMock(spec=BaseLLMClient), mevzuat_retriever=retriever
    )
    await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    mock_node_budget.assert_any_call("suggest_mevzuat", None)
    assert mock_node_budget.call_count == 1


@pytest.mark.asyncio
@patch("app.ai.agents.compliance.ComplianceAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_degrades_to_raw_citations_when_suggestion_fails(mock_classify, mock_suggest):
    """Requirement 5 is still met by the retrieved citations alone."""
    mock_classify.return_value = _merged(
        DocumentType.OFFICIAL_LETTER, "x", **COMPLETE_FIELDS.model_dump()
    )
    mock_suggest.side_effect = Exception("LLM timeout")

    retriever = AsyncMock(spec=HybridRetriever)
    retriever.retrieve.return_value = [
        Document(page_content="MADDE 11-", metadata={"mevzuat": "RYUEHY"})
    ]

    graph = create_document_analysis_graph(
        MagicMock(spec=BaseLLMClient), mevzuat_retriever=retriever
    )
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert result["mevzuat_suggestions"] == [
        {
            "mevzuat": "RYUEHY",
            "aciklama": "İlgili olabilecek mevzuat alıntısı (otomatik açıklama üretilemedi).",
        }
    ]


@pytest.mark.asyncio
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_survives_retriever_failure(mock_classify):
    mock_classify.return_value = _merged(
        DocumentType.OFFICIAL_LETTER, "x", **COMPLETE_FIELDS.model_dump()
    )

    retriever = AsyncMock(spec=HybridRetriever)
    retriever.retrieve.side_effect = Exception("Qdrant down")

    graph = create_document_analysis_graph(
        MagicMock(spec=BaseLLMClient), mevzuat_retriever=retriever
    )
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert result["mevzuat_documents"] == []
    assert result["mevzuat_suggestions"] == []
    assert result["compliance_status"] == ComplianceStatus.COMPLIANT.value


# ==========================================
# Failure isolation
# ==========================================
@pytest.mark.asyncio
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_falls_back_to_other_when_classification_fails(mock_classify):
    # Every attempt fails: the merged call and the classification-only retry
    # both go through this same mocked method with no fast-tier client to
    # fall further back to.
    mock_classify.side_effect = Exception("structured output invalid")

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": "bozuk evrak"})

    assert result["document_type"] == DocumentType.OTHER.value
    assert result["summary"] == "Evrak özeti çıkarılamadı."
    # Analysis must continue rather than raising.
    assert "compliance_status" in result


@pytest.mark.asyncio
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_survives_extraction_failure(mock_classify):
    """When the merged schema fails, the classification-only retry still yields
    a type and summary; the model contributes no fields, yet the
    deterministically parsed ones stand and only the genuinely absent ones are
    reported."""
    mock_classify.side_effect = [
        Exception("schema violation"),
        DocumentClassificationOutput(document_type=DocumentType.OFFICIAL_LETTER, summary="x"),
    ]

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": INCOMPLETE_LETTER_TEXT})

    assert result["document_type"] == DocumentType.OFFICIAL_LETTER.value
    assert result["compliance_status"] == ComplianceStatus.INCOMPLETE.value
    assert {item["key"] for item in result["missing_fields"]} == {"muhatap", "sayi"}
    assert result["fields"]["tarih"] == "30.07.2026"


@pytest.mark.asyncio
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_parser_rescues_labelled_fields_the_model_drops(mock_classify):
    """The prescribed header labels are read deterministically, so a model that
    returns nothing must not cause a false 'missing field' report."""
    mock_classify.return_value = _merged(DocumentType.OFFICIAL_LETTER, "x")  # contributes no fields

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    fields = result["fields"]
    assert fields["sayi"] == "E-123-456"
    assert fields["tarih"] == "30.07.2026"
    assert fields["konu"] == "Yıllık İzin Talebi"
    detected = {item["key"] for item in result["missing_fields"]}
    assert "sayi" not in detected
    assert "tarih" not in detected


@pytest.mark.asyncio
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_parsed_fields_survive_an_extraction_failure(mock_classify):
    """A total model failure must not discard values read straight off the document."""
    mock_classify.side_effect = Exception("structured output invalid")

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert result["fields"]["sayi"] == "E-123-456"
    assert result["fields"]["konu"] == "Yıllık İzin Talebi"


@pytest.mark.asyncio
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_parsed_values_override_model_guesses(mock_classify):
    """A label read off the document is stronger evidence than a model guess."""
    mock_classify.return_value = _merged(
        DocumentType.OFFICIAL_LETTER, "x", sayi="UYDURMA-999", konu="yanlış konu"
    )

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert result["fields"]["sayi"] == "E-123-456"
    assert result["fields"]["konu"] == "Yıllık İzin Talebi"


# ==========================================
# Sensitivity scan + guardrail judge escalation (Faz 1 + Faz 3)
# ==========================================
@pytest.mark.asyncio
@patch("app.ai.agents.guardrail_judge.GuardrailJudgeAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_a_deterministically_unflagged_document_is_not_escalated_by_a_calm_judge(
    mock_classify, mock_judge
):
    mock_classify.return_value = _merged(DocumentType.OFFICIAL_LETTER, "x")
    mock_judge.return_value = GuardrailJudgeVerdict(
        sensitive=False, confidence=0.95, reason="Sıradan yazışma."
    )

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert result["sensitivity_assessment"]["requires_review"] is False
    # #214: an unmarked document's effective level defaults to the policy
    # floor ("Tasnif Dışı") rather than staying an apparent analysis gap.
    assert result["sensitivity_assessment"]["effective_level"] == "tasnif_disi"
    assert result["sensitivity_assessment"]["is_defaulted"] is True


@pytest.mark.asyncio
@patch("app.ai.agents.guardrail_judge.GuardrailJudgeAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_the_judge_escalates_a_document_with_no_pattern_match(mock_classify, mock_judge):
    """The whole point of the nuance layer: a document with no gizlilik
    marking and no PII pattern match can still require review if the judge
    reads it as sensitive in meaning."""
    mock_classify.return_value = _merged(DocumentType.OFFICIAL_LETTER, "x")
    mock_judge.return_value = GuardrailJudgeVerdict(
        sensitive=True, confidence=0.9, reason="İzin talebinde tıbbi tanı detayı geçiyor."
    )

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert result["sensitivity_assessment"]["requires_review"] is True
    assert any(
        "llm-judge" in reason for reason in result["sensitivity_assessment"]["reasons"]
    )


@pytest.mark.asyncio
@patch("app.ai.agents.guardrail_judge.GuardrailJudgeAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_a_low_confidence_judge_verdict_does_not_escalate(mock_classify, mock_judge):
    mock_classify.return_value = _merged(DocumentType.OFFICIAL_LETTER, "x")
    mock_judge.return_value = GuardrailJudgeVerdict(
        sensitive=True, confidence=0.2, reason="Belirsiz bir izlenim."
    )

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert result["sensitivity_assessment"]["requires_review"] is False


@pytest.mark.asyncio
@patch("app.ai.agents.guardrail_judge.GuardrailJudgeAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_an_already_flagged_document_does_not_consult_the_judge(mock_classify, mock_judge):
    """A gizlilik-marked document is already routed to review -- asking the
    judge for a second opinion buys nothing and only costs latency."""
    mock_classify.return_value = _merged(
        DocumentType.OFFICIAL_LETTER, "x", gizlilik_derecesi="Gizli"
    )

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert result["sensitivity_assessment"]["requires_review"] is True
    mock_judge.assert_not_called()


@pytest.mark.asyncio
@patch("app.ai.agents.guardrail_judge.GuardrailJudgeAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_a_degraded_judge_call_leaves_the_deterministic_result_untouched(
    mock_classify, mock_judge
):
    mock_classify.return_value = _merged(DocumentType.OFFICIAL_LETTER, "x")
    mock_judge.side_effect = Exception("provider unavailable")

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert result["sensitivity_assessment"]["requires_review"] is False


#: Moved to tests/unit/ai/test_summarization.py -- detailed summarization is
#: no longer a graph node (see create_document_analysis_graph's own
#: docstring for why), so those tests now call build_detailed_summary
#: directly instead of driving a whole graph run.
