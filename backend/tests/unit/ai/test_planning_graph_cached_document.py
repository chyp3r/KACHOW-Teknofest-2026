"""Tests for `planning_graph._load_cached_document` (J9).

`app.ai.workflows.planning_graph` must never import `app.domains.*`
directly (`test_ai_never_imports_domains.py` enforces this statically), so
this function only ever delegates to an injected `document_cache_provider`
callable -- see `app.domains.documents.provider.get_cached_document` for
the real implementation these tests stand in for."""

import pytest

from app.ai.workflows.planning_graph import _load_cached_document


@pytest.mark.asyncio
async def test_returns_empty_dict_without_a_document_id():
    async def _provider(document_id: str) -> dict:
        raise AssertionError("must not be called without a document_id")

    result = await _load_cached_document(_provider, None)

    assert result == {}


@pytest.mark.asyncio
async def test_returns_empty_dict_without_a_provider():
    result = await _load_cached_document(None, "uploads/abc.pdf")

    assert result == {}


@pytest.mark.asyncio
async def test_delegates_to_the_injected_provider():
    calls = []

    async def _provider(document_id: str) -> dict:
        calls.append(document_id)
        return {"extracted_text": "metin"}

    result = await _load_cached_document(_provider, "uploads/abc.pdf")

    assert result == {"extracted_text": "metin"}
    assert calls == ["uploads/abc.pdf"]
