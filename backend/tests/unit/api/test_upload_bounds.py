"""Tests for the streaming upload size guard (D10).

``await file.read()`` used to read the entire body into memory before any
size check could run -- a 2GB upload allocated 2GB regardless of the
configured 50MB limit, since the limit was only ever checked afterwards.
``_read_bounded`` reads in bounded chunks and raises the moment the running
total crosses the limit, so worst-case memory stays bounded.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependency import get_document_analysis_service
from app.api.exceptions.validation import ValidationException
from app.domains.documents import router as documents_router
from app.domains.documents.router import _READ_CHUNK_BYTES, _read_bounded
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _fake_upload(chunks: list[bytes]):
    """A stand-in UploadFile that yields the given chunks, then EOF."""
    upload = AsyncMock()
    remaining = list(chunks) + [b""]
    upload.read.side_effect = remaining
    return upload


@pytest.mark.asyncio
async def test_read_bounded_returns_the_full_body_when_within_the_limit():
    upload = _fake_upload([b"hello ", b"world"])

    content = await _read_bounded(upload, limit=100)

    assert content == b"hello world"


@pytest.mark.asyncio
async def test_read_bounded_raises_the_moment_the_running_total_crosses_the_limit():
    upload = _fake_upload([b"a" * 10, b"b" * 10, b"c" * 10])

    with pytest.raises(ValidationException):
        await _read_bounded(upload, limit=15)


@pytest.mark.asyncio
async def test_read_bounded_never_requests_a_chunk_larger_than_configured():
    upload = _fake_upload([b"x" * 1000])

    await _read_bounded(upload, limit=10_000)

    upload.read.assert_any_call(_READ_CHUNK_BYTES)


@pytest.mark.asyncio
async def test_read_bounded_allows_a_body_exactly_at_the_limit():
    upload = _fake_upload([b"a" * 20])

    content = await _read_bounded(upload, limit=20)

    assert content == b"a" * 20


@pytest.mark.asyncio
async def test_read_bounded_stops_reading_further_chunks_once_over_limit():
    """Once the limit is exceeded, no further chunks should be pulled from the
    client -- an attacker streaming an unbounded body must not keep the
    connection (and a worker) busy past the point the limit is known to be
    violated."""
    upload = _fake_upload([b"a" * 10, b"b" * 10, b"c" * 10])

    with pytest.raises(ValidationException):
        await _read_bounded(upload, limit=15)

    assert upload.read.call_count == 2


def test_analyze_endpoint_rejects_an_oversized_declared_content_length(monkeypatch):
    monkeypatch.setattr(documents_router, "MAX_FILE_SIZE_BYTES", 5)
    service = AsyncMock()
    app.dependency_overrides[get_document_analysis_service] = lambda: service

    response = client.post(
        "/api/v1/documents/analyze",
        files={"file": ("evrak.pdf", b"this is definitely more than five bytes", "application/pdf")},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert "boyut" in body["error"]["message"]
    service.analyze_document.assert_not_called()
