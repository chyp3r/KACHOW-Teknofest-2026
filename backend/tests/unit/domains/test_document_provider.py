"""Tests for `app.domains.documents.provider.get_cached_document` (J9) --
the planning graph's injected callable for reading a document's analysis
cache through the configured storage backend, not a raw local-filesystem
path (see `cache_keys.py` and `documents/service.py::
_save_document_analysis_cache` for the bug this replaces: a document
analyzed under `STORAGE_TYPE=s3`, or served by any backend replica other
than the one that wrote it, silently lost its cached context here)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.documents import provider as provider_module
from app.domains.documents.cache_keys import analysis_cache_key


def _stub_storage_client(monkeypatch, storage):
    monkeypatch.setattr(provider_module, "get_storage_client", MagicMock(return_value=storage))


@pytest.mark.asyncio
async def test_returns_the_parsed_cache_when_present(monkeypatch):
    storage = AsyncMock()
    payload = {"extracted_text": "metin", "pages": ["metin"], "analysis": {"summary": "özet"}}
    storage.get_file.return_value = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    _stub_storage_client(monkeypatch, storage)

    result = await provider_module.get_cached_document("uploads/abc.pdf")

    assert result == payload
    storage.get_file.assert_awaited_once_with(analysis_cache_key("uploads/abc.pdf"))


@pytest.mark.asyncio
async def test_degrades_to_empty_dict_when_nothing_is_cached(monkeypatch):
    storage = AsyncMock()
    storage.get_file.side_effect = FileNotFoundError("uploads/missing.pdf_analysis.json")
    _stub_storage_client(monkeypatch, storage)

    result = await provider_module.get_cached_document("uploads/missing.pdf")

    assert result == {}


@pytest.mark.asyncio
async def test_degrades_to_empty_dict_on_a_storage_backend_error(monkeypatch):
    """A transient S3/MinIO outage must not fail the whole planning step --
    same "degrade, don't fail" contract every other optional planning-graph
    input (units_provider, adapter_provider, ...) already follows."""
    storage = AsyncMock()
    storage.get_file.side_effect = RuntimeError("endpoint unreachable")
    _stub_storage_client(monkeypatch, storage)

    result = await provider_module.get_cached_document("uploads/abc.pdf")

    assert result == {}


@pytest.mark.asyncio
async def test_degrades_to_empty_dict_on_unparseable_json(monkeypatch):
    """A half-written or corrupted cache entry is a degrade, not a 500."""
    storage = AsyncMock()
    storage.get_file.return_value = b"not json"
    _stub_storage_client(monkeypatch, storage)

    result = await provider_module.get_cached_document("uploads/abc.pdf")

    assert result == {}
