"""API tests for the document analysis endpoint."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.ai.compliance.evrak_field import EvrakField, MissingField
from app.api.dependency import get_document_analysis_service
from app.api.exceptions.ai_error import AIException
from app.api.exceptions.validation import ValidationException
from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.document_type import DocumentType
from app.domains.documents.schema.document_schema import (
    DocumentAnalysisResponseSchema,
    ExtractionInfoSchema,
    MevzuatReferenceSchema,
)
from app.main import app

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
