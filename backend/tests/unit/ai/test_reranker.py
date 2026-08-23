"""Tests for ``app.ai.retrieval.reranker.CrossEncoderReranker``.

The real ``sentence-transformers`` model is never loaded here (that would
pull in torch and a multi-hundred-MB HuggingFace download on every test
run) -- ``CrossEncoderReranker._load`` is monkeypatched to return a stub
``predict`` instead, the same boundary ``rerank()`` itself draws between
"my own ordering/degrade logic" and "the model's own scoring", so these
tests stay meaningful without the real weights. A live check against the
real model was run manually during development: for the Turkish query
"Personel görevlendirmesi hangi tarihte başlıyor?" against three candidate
passages, the genuinely relevant one ("Personelin 12 Mart 2026 tarihinde
göreve başlaması uygun görülmüştür.") scored 5.96 while the two irrelevant
ones scored -6.43 and -4.90 -- a clean, correctly-ordered separation.
"""

from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from app.ai.retrieval.reranker import BaseReranker, CrossEncoderReranker


def _docs(*texts: str) -> list[Document]:
    return [Document(page_content=text) for text in texts]


@pytest.mark.asyncio
async def test_rerank_empty_documents_returns_empty_without_loading_a_model():
    reranker = CrossEncoderReranker(model_name="unused")
    result = await reranker.rerank("query", [], top_k=5)
    assert result == []
    assert reranker._model is None


@pytest.mark.asyncio
async def test_rerank_reorders_by_descending_score(monkeypatch):
    reranker = CrossEncoderReranker(model_name="unused")
    stub_model = MagicMock()
    # Scores intentionally out of order vs. input: the third document should
    # win despite being last in the fused (input) order.
    stub_model.predict.return_value = [0.1, 0.9, 0.5]
    monkeypatch.setattr(reranker, "_load", lambda: stub_model)

    documents = _docs("low relevance", "high relevance", "medium relevance")
    result = await reranker.rerank("query", documents, top_k=3)

    assert [doc.page_content for doc in result] == [
        "high relevance",
        "medium relevance",
        "low relevance",
    ]


@pytest.mark.asyncio
async def test_rerank_truncates_to_top_k():
    reranker = CrossEncoderReranker(model_name="unused")
    stub_model = MagicMock()
    stub_model.predict.return_value = [0.3, 0.9, 0.1, 0.6]
    reranker._load = lambda: stub_model

    documents = _docs("a", "b", "c", "d")
    result = await reranker.rerank("query", documents, top_k=2)

    assert [doc.page_content for doc in result] == ["b", "d"]


def test_load_caches_the_model_on_the_instance(monkeypatch):
    """`_load()`'s own once-only caching contract -- `rerank()` always goes
    through `_load()`, so this is what makes every call after the first
    reuse the already-loaded weights rather than reloading them."""
    reranker = CrossEncoderReranker(model_name="unused")
    build_calls = []

    class _FakeCrossEncoder:
        def __init__(self, model_name):
            build_calls.append(model_name)

    fake_module = MagicMock()
    fake_module.CrossEncoder = _FakeCrossEncoder
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", fake_module)

    first = reranker._load()
    second = reranker._load()

    assert first is second
    assert len(build_calls) == 1


@pytest.mark.asyncio
async def test_rerank_degrades_to_fused_order_truncated_on_model_failure(monkeypatch):
    reranker = CrossEncoderReranker(model_name="unused")

    def _raise():
        raise RuntimeError("model failed to load")

    monkeypatch.setattr(reranker, "_load", _raise)

    documents = _docs("first", "second", "third")
    result = await reranker.rerank("query", documents, top_k=2)

    # Never raises; falls back to the pre-rerank (fused) order, truncated.
    assert [doc.page_content for doc in result] == ["first", "second"]


@pytest.mark.asyncio
async def test_rerank_degrades_when_predict_itself_raises(monkeypatch):
    reranker = CrossEncoderReranker(model_name="unused")
    stub_model = MagicMock()
    stub_model.predict.side_effect = RuntimeError("OOM")
    monkeypatch.setattr(reranker, "_load", lambda: stub_model)

    documents = _docs("first", "second")
    result = await reranker.rerank("query", documents, top_k=1)

    assert [doc.page_content for doc in result] == ["first"]


def test_cross_encoder_reranker_is_a_base_reranker():
    assert issubclass(CrossEncoderReranker, BaseReranker)
