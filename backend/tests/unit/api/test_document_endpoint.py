"""API tests for the document analysis endpoint."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.ai.compliance.evrak_field import EvrakField, MissingField
from app.api.dependency import (
    get_document_analysis_service,
    get_document_repository,
    require_auth_if_enabled,
)
from app.api.exceptions.ai_error import AIException
from app.api.exceptions.validation import ValidationException
from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.document_type import DocumentType
from app.core.enums.user_role import UserRole
from app.domains.documents.model.document_model import DocumentModel
from app.domains.documents.schema.document_schema import (
    DocumentAnalysisResponseSchema,
    DocumentTextSchema,
    ExtractionInfoSchema,
    MevzuatReferenceSchema,
)
from app.domains.users.model.user_model import UserModel
from app.infrastructure.extractors.base import DocumentExtractionError
from app.main import app

_CURRENT_USER = UserModel(
    id="admin-1",
    company_id="company-1",
    username="admin",
    email="a@a.com",
    role=UserRole.ADMIN.value,
    clearance_level="cok_gizli",
    is_active=True,
    is_deleted=False,
    hashed_password="pw",
    created_at=datetime.now(timezone.utc),
    updated_at=datetime.now(timezone.utc),
)


def _mock_document_repository():
    """A document repository stand-in that always resolves to a document
    owned by `_CURRENT_USER`'s company -- the router's ownership/company
    check (`get_by_id` + `bypasses_ownership`) must pass before the field-
    update/delete service calls this test exercises are ever reached."""
    repo = AsyncMock()
    repo.get_by_id.return_value = DocumentModel(
        id="uploads/x.pdf",
        company_id="company-1",
        owner_id="admin-1",
        file_name="evrak.pdf",
    )
    return repo

ENDPOINT = "/api/v1/documents/analyze"

ANALYSIS_RESULT = DocumentAnalysisResponseSchema(
    file_name="evrak.pdf",
    storage_path="uploads/abc.pdf",
    extraction=ExtractionInfoSchema(
        extractor="opendataloader", page_count=1, char_count=364, used_ocr=False
    ),
    document_type=DocumentType.OFFICIAL_LETTER,
    document_type_label="Resmî Yazı",
    summary="İzin talebi yazısı.",
    fields=EvrakField(sayi="E-123", konu="İzin Talebi"),
    missing_fields=[
        MissingField(
            key="muhatap",
            label="Muhatap",
            severity="zorunlu",
            mevzuat="Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik m.14",
            reason="Muhatap belirtilmelidir.",
        )
    ],
    compliance_status=ComplianceStatus.INCOMPLETE,
    mevzuat_references=[
        MevzuatReferenceSchema(mevzuat="RYUEHY m.14", aciklama="Muhatap zorunludur.")
    ],
)

client = TestClient(app, raise_server_exceptions=False)


def _override(service):
    app.dependency_overrides[get_document_analysis_service] = lambda: service
    app.dependency_overrides[require_auth_if_enabled] = lambda: _CURRENT_USER
    app.dependency_overrides[get_document_repository] = _mock_document_repository


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_analyze_returns_success_envelope():
    service = AsyncMock()
    service.analyze_document.return_value = ANALYSIS_RESULT
    _override(service)

    response = client.post(
        ENDPOINT, files={"file": ("evrak.pdf", b"%PDF-1.7 data", "application/pdf")}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["error"] is None
    assert "timestamp" in body["meta"]
    assert "X-Response-Time-Ms" in response.headers

    data = body["data"]
    assert data["document_type"] == "official_letter"
    assert data["document_type_label"] == "Resmî Yazı"
    assert data["summary"] == "İzin talebi yazısı."
    assert data["compliance_status"] == "incomplete"
    assert data["fields"]["sayi"] == "E-123"
    assert data["missing_fields"][0]["key"] == "muhatap"
    assert data["missing_fields"][0]["mevzuat"].endswith("m.14")
    assert data["mevzuat_references"][0]["mevzuat"] == "RYUEHY m.14"
    assert data["extraction"]["used_ocr"] is False


def test_analyze_passes_upload_metadata_to_the_service():
    service = AsyncMock()
    service.analyze_document.return_value = ANALYSIS_RESULT
    _override(service)

    client.post(
        ENDPOINT, files={"file": ("dilekce.png", b"\x89PNG data", "image/png")}
    )

    kwargs = service.analyze_document.await_args.kwargs
    assert kwargs["file_name"] == "dilekce.png"
    assert kwargs["content_type"] == "image/png"
    assert kwargs["content"] == b"\x89PNG data"


def test_analyze_requires_a_file():
    service = AsyncMock()
    _override(service)

    response = client.post(ENDPOINT)

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_analyze_maps_validation_exception_to_the_error_envelope():
    service = AsyncMock()
    service.analyze_document.side_effect = ValidationException(
        message="Desteklenmeyen dosya türü."
    )
    _override(service)

    response = client.post(
        ENDPOINT, files={"file": ("x.exe", b"MZ", "application/octet-stream")}
    )

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Desteklenmeyen dosya türü."


def test_analyze_maps_ai_exception_to_502():
    service = AsyncMock()
    service.analyze_document.side_effect = AIException(
        message="Evrak analizi zaman aşımına uğradı."
    )
    _override(service)

    response = client.post(
        ENDPOINT, files={"file": ("evrak.pdf", b"%PDF", "application/pdf")}
    )

    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "AI_EXECUTION_ERROR"
    assert "zaman aşımına" in body["error"]["message"]


def test_endpoint_is_registered_in_the_openapi_schema():
    spec = app.openapi()
    assert ENDPOINT in spec["paths"]
    assert "post" in spec["paths"][ENDPOINT]


# ==========================================
# PATCH /documents/{storage_path}/fields
# ==========================================
_FIELDS_STORAGE_PATH = f"uploads/{'a' * 32}.pdf"
_FIELDS_ENDPOINT = f"/api/v1/documents/{_FIELDS_STORAGE_PATH}/fields"


def test_update_fields_returns_the_recomputed_analysis():
    service = AsyncMock()
    updated = ANALYSIS_RESULT.model_copy(
        update={
            "fields": EvrakField(sayi="E-123", konu="İzin Talebi", muhatap="İlgili Makama"),
            "missing_fields": [],
            "compliance_status": ComplianceStatus.COMPLIANT,
        }
    )
    service.update_document_fields.return_value = updated
    _override(service)

    response = client.patch(
        _FIELDS_ENDPOINT,
        json={"fields": {"sayi": "E-123", "konu": "İzin Talebi", "muhatap": "İlgili Makama"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["fields"]["muhatap"] == "İlgili Makama"
    assert body["data"]["missing_fields"] == []
    assert body["data"]["compliance_status"] == "compliant"
    kwargs = service.update_document_fields.await_args.args
    assert kwargs[0] == _FIELDS_STORAGE_PATH
    assert kwargs[1].muhatap == "İlgili Makama"


def test_update_fields_returns_404_when_nothing_is_cached():
    service = AsyncMock()
    service.update_document_fields.return_value = None
    _override(service)

    response = client.patch(_FIELDS_ENDPOINT, json={"fields": {}})

    assert response.status_code == 404


# ==========================================
# POST /documents/{storage_path}/detailed-summary
# ==========================================
_SUMMARY_STORAGE_PATH = f"uploads/{'b' * 32}.pdf"
_SUMMARY_ENDPOINT = f"/api/v1/documents/{_SUMMARY_STORAGE_PATH}/detailed-summary"


@pytest.fixture
def _unmetered_rate_limit():
    """Bypass the endpoint's real Redis-backed rate limiter (5 req/60s) via
    its own documented fail-open path (see rate_limit's own comment: "Fail
    open, not closed... if the counter is unreachable... the safe answer is
    to serve it") -- not a test-only shortcut, the same degradation
    production takes when Redis is briefly unavailable. Without this,
    repeated runs of this file within the same 60s window (routine during
    active development) start returning 429 instead of exercising the mocked
    service at all, exactly the mechanism already known to make
    test_analyze_maps_ai_exception_to_502 and
    test_upload_bounds.py::test_analyze_endpoint_rejects_an_oversized_declared_content_length
    order-dependently flaky against /analyze's own rate limit."""
    with patch("app.api.rate_limit.get_cache") as mock_get_cache:
        mock_get_cache.return_value.connect = AsyncMock(side_effect=Exception("test: no redis"))
        yield


def test_generate_detailed_summary_returns_the_populated_analysis(_unmetered_rate_limit):
    service = AsyncMock()
    updated = ANALYSIS_RESULT.model_copy(
        update={"detailed_summary": "Çok paragraflı ayrıntılı özet."}
    )
    service.generate_detailed_summary.return_value = updated
    _override(service)

    response = client.post(_SUMMARY_ENDPOINT)

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["detailed_summary"] == "Çok paragraflı ayrıntılı özet."
    assert service.generate_detailed_summary.await_args.args == (_SUMMARY_STORAGE_PATH,)


def test_generate_detailed_summary_returns_404_when_nothing_is_cached(_unmetered_rate_limit):
    service = AsyncMock()
    service.generate_detailed_summary.return_value = None
    _override(service)

    response = client.post(_SUMMARY_ENDPOINT)

    assert response.status_code == 404


def test_generate_detailed_summary_surfaces_a_generation_failure_as_502(_unmetered_rate_limit):
    """AIException (timeout or provider failure -- see
    DocumentService.generate_detailed_summary's own docstring for why this
    raises rather than degrading silently) must reach the caller as a clear
    502, not a generic 500 or a silently empty 200."""
    service = AsyncMock()
    service.generate_detailed_summary.side_effect = AIException(
        message="Ayrıntılı özet oluşturma zaman aşımına uğradı."
    )
    _override(service)

    response = client.post(_SUMMARY_ENDPOINT)

    assert response.status_code == 502


# ==========================================
# GET/PUT /documents/{storage_path}/text, POST /documents/{storage_path}/re-extract
# ==========================================
_TEXT_STORAGE_PATH = f"uploads/{'c' * 32}.pdf"
_TEXT_ENDPOINT = f"/api/v1/documents/{_TEXT_STORAGE_PATH}/text"
_REEXTRACT_ENDPOINT = f"/api/v1/documents/{_TEXT_STORAGE_PATH}/re-extract"

TEXT_RESULT = DocumentTextSchema(
    pages=["Sayı : E-123", "İkinci sayfa"],
    extracted_text="Sayı : E-123\n\nİkinci sayfa",
    page_count=2,
    extractor="tesseract",
    used_ocr=True,
)


def test_get_document_text_returns_the_cached_pages():
    service = AsyncMock()
    service.get_document_text.return_value = TEXT_RESULT
    _override(service)

    response = client.get(_TEXT_ENDPOINT)

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["pages"] == ["Sayı : E-123", "İkinci sayfa"]
    assert body["extractor"] == "tesseract"
    assert service.get_document_text.await_args.args == (_TEXT_STORAGE_PATH,)


def test_get_document_text_returns_404_when_nothing_is_cached():
    service = AsyncMock()
    service.get_document_text.return_value = None
    _override(service)

    response = client.get(_TEXT_ENDPOINT)

    assert response.status_code == 404


def test_get_document_text_is_not_swallowed_by_the_catch_all_get_route():
    """/{storage_path:path} is greedy; a GET sub-route must be declared
    above it in router.py, or it silently returns the full analysis shape
    instead of the text view (or worse, treats '.../text' as itself a
    storage_path and 404s confusingly)."""
    service = AsyncMock()
    service.get_document_text.return_value = TEXT_RESULT
    service.get_cached_analysis.return_value = ANALYSIS_RESULT
    _override(service)

    response = client.get(_TEXT_ENDPOINT)

    assert response.status_code == 200
    body = response.json()["data"]
    assert "pages" in body
    assert "document_type" not in body
    service.get_cached_analysis.assert_not_called()
    service.get_document_text.assert_awaited_once()


def test_get_document_text_rejects_a_malformed_storage_path():
    service = AsyncMock()
    _override(service)

    response = client.get("/api/v1/documents/..%2Fetc/text")

    assert response.status_code == 400


def test_update_document_text_returns_the_recomputed_analysis(_unmetered_rate_limit):
    service = AsyncMock()
    updated = ANALYSIS_RESULT.model_copy(
        update={
            "fields": EvrakField(sayi="E-123", konu="İzin Talebi", muhatap="İlgili Makama")
        }
    )
    service.update_document_text.return_value = updated
    _override(service)

    response = client.put(
        _TEXT_ENDPOINT, json={"pages": ["Sayı : E-123", "Konu : İzin Talebi"]}
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["fields"]["muhatap"] == "İlgili Makama"
    args = service.update_document_text.await_args.args
    assert args[0] == _TEXT_STORAGE_PATH
    assert args[1] == ["Sayı : E-123", "Konu : İzin Talebi"]


def test_update_document_text_returns_404_when_nothing_is_cached(_unmetered_rate_limit):
    service = AsyncMock()
    service.update_document_text.return_value = None
    _override(service)

    response = client.put(_TEXT_ENDPOINT, json={"pages": ["x"]})

    assert response.status_code == 404


def test_update_document_text_surfaces_a_page_count_mismatch_as_422(_unmetered_rate_limit):
    service = AsyncMock()
    service.update_document_text.side_effect = ValidationException(
        message="Sayfa sayısı önbellekteki belgeyle eşleşmiyor."
    )
    _override(service)

    response = client.put(_TEXT_ENDPOINT, json={"pages": ["x", "y"]})

    assert response.status_code == 422


def test_reextract_document_text_returns_the_recomputed_analysis(_unmetered_rate_limit):
    service = AsyncMock()
    updated = ANALYSIS_RESULT.model_copy(
        update={
            "extraction": ExtractionInfoSchema(
                extractor="ollama_vision", page_count=1, char_count=100, used_ocr=True
            )
        }
    )
    service.reextract_document_text.return_value = updated
    _override(service)

    response = client.post(_REEXTRACT_ENDPOINT)

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["extraction"]["extractor"] == "ollama_vision"
    assert service.reextract_document_text.await_args.args == (
        _TEXT_STORAGE_PATH,
        "company-1",
    )


def test_reextract_document_text_returns_404_when_nothing_is_cached(_unmetered_rate_limit):
    service = AsyncMock()
    service.reextract_document_text.return_value = None
    _override(service)

    response = client.post(_REEXTRACT_ENDPOINT)

    assert response.status_code == 404


def test_reextract_document_text_maps_extraction_failure_to_422(_unmetered_rate_limit):
    service = AsyncMock()
    service.reextract_document_text.side_effect = DocumentExtractionError(
        "model unreachable"
    )
    _override(service)

    response = client.post(_REEXTRACT_ENDPOINT)

    assert response.status_code == 422
