"""Unit tests for the document analysis domain service."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.exceptions.ai_error import AIException
from app.api.exceptions.validation import ValidationException
from app.core.constants import MAX_FILE_SIZE_BYTES
from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.document_type import DocumentType
from app.domains.documents.service import DocumentService
from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
)
from app.infrastructure.storage.base import BaseStorage

PDF_BYTES = b"%PDF-1.7" + b"x" * 500

GRAPH_STATE = {
    "document_type": DocumentType.OFFICIAL_LETTER.value,
    "document_type_label": "Resmî Yazı",
    "summary": "İzin talebi yazısı.",
    "fields": {"sayi": "E-123", "konu": "İzin"},
    "missing_fields": [
        {
            "key": "muhatap",
            "label": "Muhatap",
            "severity": "zorunlu",
            "mevzuat": "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik m.14",
            "reason": "Muhatap belirtilmelidir.",
        }
    ],
    "compliance_status": ComplianceStatus.INCOMPLETE.value,
    "mevzuat_suggestions": [
        {"mevzuat": "RYUEHY m.14", "aciklama": "Muhatap zorunludur."}
    ],
}


def _build_service(
    extracted: ExtractedDocument | None = None,
    graph_state: dict | None = None,
    extractor_error: Exception | None = None,
    graph_error: Exception | None = None,
):
    storage = AsyncMock(spec=BaseStorage)
    storage.put_file.return_value = "uploads/abc.pdf"

    extractor = AsyncMock(spec=BaseDocumentExtractor)
    if extractor_error is not None:
        extractor.extract.side_effect = extractor_error
    else:
        extractor.extract.return_value = extracted or ExtractedDocument(
            text="Sayı: E-123\nKonu: İzin\n" + "x" * 300,
            pages=["p1"],
            page_count=1,
            extractor="opendataloader",
        )

    graph = MagicMock()
    if graph_error is not None:
        graph.ainvoke = AsyncMock(side_effect=graph_error)
    else:
        graph.ainvoke = AsyncMock(return_value=graph_state or GRAPH_STATE)

    service = DocumentService(storage=storage, extractor=extractor, analysis_graph=graph)
    return service, storage, extractor, graph


# ==========================================
# Happy path
# ==========================================
@pytest.mark.asyncio
async def test_analyze_returns_full_first_review_result():
    service, storage, _, _ = _build_service()

    result = await service.analyze_document(
        file_name="evrak.pdf", content=PDF_BYTES, content_type="application/pdf"
    )

    assert result.file_name == "evrak.pdf"
    assert result.storage_path == "uploads/abc.pdf"
    assert result.document_type is DocumentType.OFFICIAL_LETTER
    assert result.document_type_label == "Resmî Yazı"
    assert result.summary == "İzin talebi yazısı."
    assert result.fields.sayi == "E-123"
    assert [item.key for item in result.missing_fields] == ["muhatap"]
    assert result.missing_fields[0].mevzuat.endswith("m.14")
    assert result.compliance_status is ComplianceStatus.INCOMPLETE
    assert result.mevzuat_references[0].mevzuat == "RYUEHY m.14"
    assert result.extraction.extractor == "opendataloader"
    assert result.extraction.used_ocr is False

    storage.put_file.assert_awaited_once()
    assert storage.put_file.await_args.args[0].startswith("uploads/")
    assert storage.put_file.await_args.args[0].endswith(".pdf")


@pytest.mark.asyncio
async def test_analyze_propagates_ocr_flag_into_the_workflow():
    """The UI must be able to warn that fields came from OCR."""
    extracted = ExtractedDocument(
        text="taranmis metin " * 40,
        page_count=1,
        extractor="tesseract",
        used_ocr=True,
    )
    service, _, _, graph = _build_service(extracted=extracted)

    result = await service.analyze_document(
        file_name="evrak.png", content=b"\x89PNG" + b"x" * 500, content_type="image/png"
    )

    assert result.extraction.used_ocr is True
    assert graph.ainvoke.await_args.args[0]["is_ocr_text"] is True


@pytest.mark.asyncio
async def test_analyze_publishes_upload_and_analyzed_events():
    service, _, _, _ = _build_service()
    published = []

    async def capture(event):
        published.append(event.event_type)

    with patch("app.domains.documents.service.event_bus") as mock_bus:
        mock_bus.publish = AsyncMock(side_effect=capture)
        await service.analyze_document(
            file_name="evrak.pdf", content=PDF_BYTES, content_type="application/pdf"
        )

    assert published == ["document.uploaded", "document.analyzed"]


@pytest.mark.asyncio
async def test_analyze_survives_event_listener_failure():
    """A broken listener must not fail document intake."""
    service, _, _, _ = _build_service()
    with patch("app.domains.documents.service.event_bus") as mock_bus:
        mock_bus.publish = AsyncMock(side_effect=Exception("listener exploded"))
        result = await service.analyze_document(
            file_name="evrak.pdf", content=PDF_BYTES, content_type="application/pdf"
        )
    assert result.document_type is DocumentType.OFFICIAL_LETTER


# ==========================================
# Upload validation
# ==========================================
@pytest.mark.asyncio
async def test_analyze_rejects_empty_file():
    service, _, _, _ = _build_service()
    with pytest.raises(ValidationException) as exc_info:
        await service.analyze_document(file_name="evrak.pdf", content=b"")
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_analyze_rejects_oversize_file():
    service, _, _, _ = _build_service()
    with pytest.raises(ValidationException) as exc_info:
        await service.analyze_document(
            file_name="evrak.pdf",
            content=b"\0" * (MAX_FILE_SIZE_BYTES + 1),
            content_type="application/pdf",
        )
    assert exc_info.value.details["max_size_bytes"] == MAX_FILE_SIZE_BYTES


@pytest.mark.asyncio
async def test_analyze_rejects_unsupported_type():
    service, _, _, _ = _build_service()
    with pytest.raises(ValidationException) as exc_info:
        await service.analyze_document(
            file_name="virus.exe",
            content=b"MZ" + b"x" * 100,
            content_type="application/octet-stream",
        )
    assert "Desteklenmeyen" in exc_info.value.message


@pytest.mark.asyncio
async def test_analyze_accepts_file_with_allowed_extension_and_no_mime():
    """Some clients omit content-type; the extension must still let it through."""
    service, _, _, _ = _build_service()
    result = await service.analyze_document(
        file_name="evrak.pdf", content=PDF_BYTES, content_type=None
    )
    assert result.document_type is DocumentType.OFFICIAL_LETTER


# ==========================================
# Failure translation
# ==========================================
@pytest.mark.asyncio
async def test_analyze_translates_extraction_failure_to_validation_error():
    service, _, _, _ = _build_service(
        extractor_error=DocumentExtractionError("Java yok")
    )
    with pytest.raises(ValidationException) as exc_info:
        await service.analyze_document(
            file_name="evrak.pdf", content=PDF_BYTES, content_type="application/pdf"
        )
    assert exc_info.value.details["reason"] == "Java yok"


@pytest.mark.asyncio
async def test_analyze_rejects_document_with_no_usable_text():
    service, _, _, _ = _build_service(
        extracted=ExtractedDocument(text="ab", page_count=1, extractor="pdfium")
    )
    with pytest.raises(ValidationException) as exc_info:
        await service.analyze_document(
            file_name="evrak.pdf", content=PDF_BYTES, content_type="application/pdf"
        )
    assert exc_info.value.details["char_count"] == 2


@pytest.mark.asyncio
async def test_analyze_wraps_workflow_failure_in_ai_exception():
    service, _, _, _ = _build_service(graph_error=RuntimeError("ollama down"))
    with pytest.raises(AIException) as exc_info:
        await service.analyze_document(
            file_name="evrak.pdf", content=PDF_BYTES, content_type="application/pdf"
        )
    assert exc_info.value.error_code == "AI_EXECUTION_ERROR"
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_analyze_wraps_timeout_in_ai_exception():
    service, _, _, _ = _build_service(graph_error=asyncio.TimeoutError())
    with pytest.raises(AIException) as exc_info:
        await service.analyze_document(
            file_name="evrak.pdf", content=PDF_BYTES, content_type="application/pdf"
        )
    assert "zaman aşımına" in exc_info.value.message


@pytest.mark.asyncio
async def test_analyze_falls_back_when_workflow_returns_unknown_enum_values():
    service, _, _, _ = _build_service(
        graph_state={"document_type": "uydurma_tur", "compliance_status": "belirsiz"}
    )
    result = await service.analyze_document(
        file_name="evrak.pdf", content=PDF_BYTES, content_type="application/pdf"
    )
    assert result.document_type is DocumentType.OTHER
    assert result.compliance_status is ComplianceStatus.INCOMPLETE


@pytest.mark.asyncio
async def test_trace_config_degrades_gracefully_without_langfuse():
    """Langfuse needs the monolithic langchain package; absence must not 500."""
    config = DocumentService._trace_config()
    assert isinstance(config, dict)
