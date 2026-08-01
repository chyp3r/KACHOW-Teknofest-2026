"""Unit tests for the incoming-document (evrak) analysis workflow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from app.ai.compliance import EvrakField
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
    """BM25 matches literal regulation tokens, so the type label and konu
    drive the query, plus a fixed suffix of mandatory-element vocabulary
    ("sayı tarih konu ilgi imza gizlilik derecesi") that gives the sparse
    retriever literal regulation terms regardless of which fields are
    actually missing."""
    state = {
        "document_type_label": "Resmî Yazı",
        "fields": {"konu": "İzin Talebi"},
        "missing_fields": [{"label": "Sayı"}, {"label": "İlgi"}],
    }
    query = _build_mevzuat_query(state)

    assert "Resmî Yazı" in query
    assert "İzin Talebi" in query
    assert "sayı" in query
    assert "ilgi" in query
    assert _build_mevzuat_query(state) == query


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
            metadata={"mevzuat": "Resmî Yazışmalar Yönetmeliği"},
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
