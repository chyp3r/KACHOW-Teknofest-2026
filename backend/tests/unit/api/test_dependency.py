"""Unit tests for the document-analysis legislation retriever's source switch.

get_document_analysis_mevzuat_retriever is the one place MEVZUAT_SOURCE is
read to decide what document analysis's retrieve_mevzuat_node actually talks
to. get_mevzuat_retriever (the plain local HybridRetriever singleton) also
backs the general assistant's RAG flow (get_rag_graph, Görev 3) -- which
MEVZUAT_SOURCE must not affect, so these tests also pin that boundary down.
"""

from unittest.mock import AsyncMock, patch

import pytest

import app.api.dependency as dependency
from app.ai.retrieval.mcp_mevzuat import FallbackMevzuatRetriever


@pytest.fixture(autouse=True)
def _clean_singletons():
    """These are module-level lazy singletons; leaking one between tests
    would make a later test see an earlier test's cached retriever instead
    of building its own under its own patched settings."""
    dependency._document_analysis_mevzuat_retriever = None
    yield
    dependency._document_analysis_mevzuat_retriever = None


@pytest.mark.asyncio
async def test_mcp_source_wraps_the_local_retriever_in_a_fallback():
    local = AsyncMock()
    with patch("app.api.dependency.settings.MEVZUAT_SOURCE", "mcp"):
        retriever = await dependency.get_document_analysis_mevzuat_retriever(local)

    assert isinstance(retriever, FallbackMevzuatRetriever)
    assert retriever._fallback is local


@pytest.mark.asyncio
async def test_local_source_returns_the_local_retriever_directly():
    local = AsyncMock()
    with patch("app.api.dependency.settings.MEVZUAT_SOURCE", "local"):
        retriever = await dependency.get_document_analysis_mevzuat_retriever(local)

    assert retriever is local


@pytest.mark.asyncio
async def test_the_retriever_is_built_once_per_process():
    local = AsyncMock()
    with patch("app.api.dependency.settings.MEVZUAT_SOURCE", "mcp"):
        first = await dependency.get_document_analysis_mevzuat_retriever(local)
        second = await dependency.get_document_analysis_mevzuat_retriever(local)

    assert first is second
