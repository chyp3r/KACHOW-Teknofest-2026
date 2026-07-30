"""Unit tests for the incoming-document (evrak) analysis workflow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from app.ai.compliance import EvrakField
from app.ai.llms.base import BaseLLMClient
from app.ai.retrieval.hybrid import HybridRetriever
from app.ai.workflows.document_analysis_graph import (
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

COMPLETE_FIELDS = EvrakField(
    sayi="E-123-456",
    tarih="30.07.2026",
    konu="Yıllık İzin Talebi",
    muhatap="İLGİLİ MAKAMA",
    gonderen_kurum="Örnek Bakanlığı",
    imza_sahibi="Mehmet Öztürk",
    imza_unvani="Genel Müdür",
)


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
    """BM25 matches literal regulation tokens, so labels drive the query."""
    state = {
        "document_type_label": "Resmî Yazı",
        "fields": {"konu": "İzin Talebi"},
        "missing_fields": [{"label": "Sayı"}, {"label": "İlgi"}],
    }
    query = _build_mevzuat_query(state)

    assert "Resmî Yazı" in query
    assert "İzin Talebi" in query
    assert "Sayı" in query
    assert "İlgi" in query
    assert _build_mevzuat_query(state) == query


def test_mevzuat_query_tolerates_empty_state():
    assert _build_mevzuat_query({}) == "resmî yazı"


# ==========================================
# Graph without a retriever
# ==========================================
@pytest.mark.asyncio
@patch("app.ai.agents.metadata.MetadataAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_detects_missing_fields_without_retriever(
    mock_classify, mock_extract
):
    mock_classify.return_value = DocumentClassificationOutput(
        document_type=DocumentType.OFFICIAL_LETTER, summary="İzin talebi yazısı."
    )
    mock_extract.return_value = COMPLETE_FIELDS.model_copy(
        update={"sayi": None, "muhatap": "Belirtilmemiş"}
    )

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert result["document_type"] == DocumentType.OFFICIAL_LETTER.value
    assert result["document_type_label"] == "Resmî Yazı"
    assert result["summary"] == "İzin talebi yazısı."
    assert result["compliance_status"] == ComplianceStatus.INCOMPLETE.value
    # "Belirtilmemiş" must count as absent, not as a value.
    assert {item["key"] for item in result["missing_fields"]} == {"sayi", "muhatap"}
    assert result["missing_fields"][0]["mevzuat"]
    assert result["mevzuat_documents"] == []
    assert result["mevzuat_suggestions"] == []


@pytest.mark.asyncio
@patch("app.ai.agents.metadata.MetadataAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_reports_compliant_document(mock_classify, mock_extract):
    mock_classify.return_value = DocumentClassificationOutput(
        document_type=DocumentType.OFFICIAL_LETTER, summary="Tam evrak."
    )
    mock_extract.return_value = COMPLETE_FIELDS

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert result["compliance_status"] == ComplianceStatus.COMPLIANT.value
    assert result["missing_fields"] == []


@pytest.mark.asyncio
@patch("app.ai.agents.metadata.MetadataAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_passes_extraction_temperature_zero(mock_classify, mock_extract):
    """Run-to-run reproducibility requires temperature 0, not the 0.7 default."""
    mock_classify.return_value = DocumentClassificationOutput(
        document_type=DocumentType.PETITION, summary="Dilekçe."
    )
    mock_extract.return_value = EvrakField()

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    await graph.ainvoke({"input_text": "dilekçe metni"})

    assert mock_classify.call_args.kwargs["temperature"] == 0.0
    assert mock_extract.call_args.kwargs["temperature"] == 0.0
    assert mock_extract.call_args.kwargs["num_ctx"] == 8192


@pytest.mark.asyncio
@patch("app.ai.agents.metadata.MetadataAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_adds_ocr_warning_to_prompts(mock_classify, mock_extract):
    mock_classify.return_value = DocumentClassificationOutput(
        document_type=DocumentType.OTHER, summary="x"
    )
    mock_extract.return_value = EvrakField()

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    await graph.ainvoke({"input_text": "taranmış metin", "is_ocr_text": True})

    assert "OCR" in mock_extract.call_args.kwargs["messages"]


# ==========================================
# Graph with a retriever
# ==========================================
@pytest.mark.asyncio
@patch("app.ai.agents.compliance.ComplianceAgent.run_structured")
@patch("app.ai.agents.metadata.MetadataAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_suggests_mevzuat_from_retrieved_excerpts(
    mock_classify, mock_extract, mock_suggest
):
    mock_classify.return_value = DocumentClassificationOutput(
        document_type=DocumentType.OFFICIAL_LETTER, summary="İzin talebi."
    )
    mock_extract.return_value = COMPLETE_FIELDS.model_copy(update={"sayi": None})
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
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert len(result["mevzuat_suggestions"]) == 1
    assert "m.11" in result["mevzuat_suggestions"][0]["mevzuat"]
    # The query must be built from the missing-field label, proving determinism.
    assert "Sayı" in retriever.retrieve.call_args.args[0]


@pytest.mark.asyncio
@patch("app.ai.agents.compliance.ComplianceAgent.run_structured")
@patch("app.ai.agents.metadata.MetadataAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_degrades_to_raw_citations_when_suggestion_fails(
    mock_classify, mock_extract, mock_suggest
):
    """Requirement 5 is still met by the retrieved citations alone."""
    mock_classify.return_value = DocumentClassificationOutput(
        document_type=DocumentType.OFFICIAL_LETTER, summary="x"
    )
    mock_extract.return_value = COMPLETE_FIELDS
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
@patch("app.ai.agents.metadata.MetadataAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_survives_retriever_failure(mock_classify, mock_extract):
    mock_classify.return_value = DocumentClassificationOutput(
        document_type=DocumentType.OFFICIAL_LETTER, summary="x"
    )
    mock_extract.return_value = COMPLETE_FIELDS

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
@patch("app.ai.agents.metadata.MetadataAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_falls_back_to_other_when_classification_fails(
    mock_classify, mock_extract
):
    mock_classify.side_effect = Exception("structured output invalid")
    mock_extract.return_value = EvrakField(konu="Bir konu")

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": "bozuk evrak"})

    assert result["document_type"] == DocumentType.OTHER.value
    assert result["summary"] == "Evrak özeti çıkarılamadı."
    # Analysis must continue rather than raising.
    assert "compliance_status" in result


@pytest.mark.asyncio
@patch("app.ai.agents.metadata.MetadataAgent.run_structured")
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
async def test_graph_survives_extraction_failure(mock_classify, mock_extract):
    mock_classify.return_value = DocumentClassificationOutput(
        document_type=DocumentType.OFFICIAL_LETTER, summary="x"
    )
    mock_extract.side_effect = Exception("schema violation")

    graph = create_document_analysis_graph(MagicMock(spec=BaseLLMClient))
    result = await graph.ainvoke({"input_text": OFFICIAL_LETTER_TEXT})

    assert result["compliance_status"] == ComplianceStatus.INCOMPLETE.value
    assert len(result["missing_fields"]) > 0
