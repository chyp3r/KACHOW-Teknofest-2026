"""Unit tests for persisting an evrak analysis to PostgreSQL and reading it back.

The repository is mocked here; the SQL it emits is exercised against a real
PostgreSQL instance by the migration and by the integration path, not by this suite.

The behaviour that matters most is the degradation: analysis must not depend on the
database being reachable, because the local JSON cache still carries the result.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.document_type import DocumentType
from app.domains.documents.model.document_model import DocumentModel
from app.domains.documents.repository import DocumentRepository
from app.domains.documents.service import DocumentService
from app.infrastructure.extractors.base import BaseDocumentExtractor, ExtractedDocument
from app.infrastructure.storage.base import BaseStorage

PDF_BYTES = b"%PDF-1.7" + b"x" * 500

GRAPH_STATE = {
    "document_type": DocumentType.CIRCULAR.value,
    "document_type_label": "Genelge",
    "summary": "Mesai saatleri uygulamasına ilişkin genelge.",
    "fields": {"sayi": "E-11111111-010.06-1204", "konu": "Mesai Saatleri"},
    "missing_fields": [],
    "compliance_status": ComplianceStatus.COMPLIANT.value,
    "mevzuat_suggestions": [{"mevzuat": "RYUEHY m.11", "aciklama": "Sayı zorunludur."}],
}


def _stored_record(**overrides) -> DocumentModel:
    defaults = dict(
        # created_at/updated_at are server defaults, so an instance that has never
        # been flushed carries None; supply them the way PostgreSQL would.
        created_at=datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc),
        storage_path="uploads/abc.pdf",
        user_id=None,
        file_name="evrak_09.pdf",
        content_type="application/pdf",
        extractor="opendataloader",
        used_ocr=False,
        page_count=1,
        char_count=348,
        document_type=DocumentType.CIRCULAR.value,
        document_type_label="Genelge",
        summary="Mesai saatleri uygulamasına ilişkin genelge.",
        fields={"sayi": "E-11111111-010.06-1204"},
        missing_fields=[],
        mevzuat_references=[{"mevzuat": "RYUEHY m.11", "aciklama": "Sayı zorunludur."}],
        scrubbed_markers=[],
        compliance_status=ComplianceStatus.COMPLIANT.value,
        extracted_text="metin",
        status="completed",
    )
    defaults.update(overrides)
    return DocumentModel(**defaults)


def _build_service(repository=None, monkeypatch=None):
    storage = AsyncMock(spec=BaseStorage)
    storage.put_file.return_value = "uploads/abc.pdf"

    extractor = AsyncMock(spec=BaseDocumentExtractor)
    extractor.extract.return_value = ExtractedDocument(
        text="Sayı: E-11111111-010.06-1204\nKonu: Mesai Saatleri\n" + "x" * 300,
        page_count=1,
        extractor="opendataloader",
    )

    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value=GRAPH_STATE)

    service = DocumentService(
        storage=storage,
        extractor=extractor,
        analysis_graph=graph,
        repository=repository,
    )
    # The local JSON writes are a separate concern and touch the filesystem.
    service._save_document_metadata = AsyncMock()
    service._save_document_analysis_cache = AsyncMock()
    return service


# ==========================================
# Writing
# ==========================================
@pytest.mark.asyncio
async def test_analysis_is_written_to_the_database():
    repository = AsyncMock(spec=DocumentRepository)
    repository.upsert.side_effect = lambda record: record
    service = _build_service(repository)

    await service.analyze_document(
        file_name="evrak_09.pdf", content=PDF_BYTES, content_type="application/pdf"
    )

    repository.upsert.assert_awaited_once()
    stored = repository.upsert.await_args.args[0]
    assert stored.storage_path == "uploads/abc.pdf"
    assert stored.document_type == DocumentType.CIRCULAR.value
    assert stored.fields["sayi"] == "E-11111111-010.06-1204"
    assert stored.mevzuat_references[0]["mevzuat"] == "RYUEHY m.11"
    assert stored.extracted_text


@pytest.mark.asyncio
async def test_a_database_failure_does_not_lose_the_analysis():
    """The analysis already succeeded and the local cache still holds it; a database
    outage must not turn a good result into a 500."""
    repository = AsyncMock(spec=DocumentRepository)
    repository.upsert.side_effect = RuntimeError("connection refused")
    service = _build_service(repository)

    result = await service.analyze_document(
        file_name="evrak_09.pdf", content=PDF_BYTES
    )

    assert result.document_type is DocumentType.CIRCULAR
    assert result.summary
    # The local fallback still ran.
    service._save_document_analysis_cache.assert_awaited_once()


@pytest.mark.asyncio
async def test_analysis_runs_with_no_repository_configured():
    service = _build_service(repository=None)

    result = await service.analyze_document(
        file_name="evrak_09.pdf", content=PDF_BYTES
    )

    assert result.document_type is DocumentType.CIRCULAR


# ==========================================
# Reading
# ==========================================
@pytest.mark.asyncio
async def test_stored_analysis_rebuilds_the_same_response_shape():
    repository = AsyncMock(spec=DocumentRepository)
    repository.get_by_storage_path.return_value = _stored_record()
    service = _build_service(repository)

    result = await service.get_stored_analysis("uploads/abc.pdf")

    assert result.analysis_id == "uploads/abc.pdf"
    assert result.storage_path == "uploads/abc.pdf"
    assert result.document_type is DocumentType.CIRCULAR
    assert result.compliance_status is ComplianceStatus.COMPLIANT
    assert result.fields.sayi == "E-11111111-010.06-1204"
    assert result.mevzuat_references[0].mevzuat == "RYUEHY m.11"
    assert result.extraction.extractor == "opendataloader"


@pytest.mark.asyncio
async def test_unknown_storage_path_reads_as_none():
    """None rather than an exception: the router falls back to the local cache."""
    repository = AsyncMock(spec=DocumentRepository)
    repository.get_by_storage_path.return_value = None
    service = _build_service(repository)

    assert await service.get_stored_analysis("uploads/nope.pdf") is None


@pytest.mark.asyncio
async def test_an_unreachable_database_reads_as_none_not_an_error():
    repository = AsyncMock(spec=DocumentRepository)
    repository.get_by_storage_path.side_effect = RuntimeError("connection refused")
    service = _build_service(repository)

    assert await service.get_stored_analysis("uploads/abc.pdf") is None


@pytest.mark.asyncio
async def test_listing_returns_the_seven_key_library_projection():
    """The frontend's library view reads these exact keys; changing them silently
    would break it, since the local JSON file produced the same shape."""
    repository = AsyncMock(spec=DocumentRepository)
    repository.get_page.return_value = ([_stored_record()], 1)
    service = _build_service(repository)

    items, total = await service.list_stored_documents(limit=5)

    assert total == 1
    assert set(items[0]) == {
        "file_name",
        "storage_path",
        "upload_time",
        "document_type",
        "document_type_label",
        "compliance_status",
        "summary",
    }
    assert items[0]["upload_time"].startswith("2026-08-04")


@pytest.mark.asyncio
async def test_listing_falls_back_when_the_database_is_unreachable():
    """None signals the router to read the local metadata file instead."""
    repository = AsyncMock(spec=DocumentRepository)
    repository.get_page.side_effect = RuntimeError("connection refused")
    service = _build_service(repository)

    assert await service.list_stored_documents(limit=5) is None


@pytest.mark.asyncio
async def test_listing_falls_back_when_no_repository_is_configured():
    service = _build_service(repository=None)

    assert await service.list_stored_documents(limit=5) is None
