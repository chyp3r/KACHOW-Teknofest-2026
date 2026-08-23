from dataclasses import replace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.documents import Document

from app.ai.policy import get_policy
from app.ai.retrieval import (
    DenseRetriever,
    BM25Retriever,
    reciprocal_rank_fusion,
    HybridRetriever,
)
from app.ai.retrieval.reranker import BaseReranker
from app.infrastructure.vectorstore import BaseVectorStore
from app.ai.embeddings import BaseEmbeddingsClient


# ==========================================
# Dense Retriever Tests
# ==========================================
@pytest.mark.asyncio
async def test_dense_retriever():
    mock_vector_store = AsyncMock(spec=BaseVectorStore)
    mock_hit = {"text": "Semantic search result", "score": 0.85, "metadata": {"source": "manual"}}
    mock_vector_store.similarity_search.return_value = [mock_hit]

    mock_embeddings = MagicMock(spec=BaseEmbeddingsClient)
    mock_embeddings.embed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])

    retriever = DenseRetriever(
        vector_store=mock_vector_store,
        embeddings_client=mock_embeddings,
        collection_name="docs"
    )

    results = await retriever.retrieve("What is NLP?", limit=1)
    
    assert len(results) == 1
    assert results[0].page_content == "Semantic search result"
    assert results[0].metadata["score"] == 0.85
    assert results[0].metadata["source"] == "manual"
    mock_vector_store.similarity_search.assert_called_once()


# ==========================================
# BM25 Retriever Tests
# ==========================================
@pytest.mark.asyncio
async def test_bm25_retriever():
    retriever = BM25Retriever()
    
    # Turkish character casing test
    docs = [
        Document(page_content="Şeker pancarı üretimi Türkiye'de çok yaygındır.", metadata={"id": 1}),
        Document(page_content="Yapay zekâ ve NLP projeleri hız kazanıyor.", metadata={"id": 2}),
        Document(page_content="Üçüncü örnek doküman.", metadata={"id": 3}),
        Document(page_content="Dördüncü örnek doküman.", metadata={"id": 4}),
        Document(page_content="Beşinci örnek doküman.", metadata={"id": 5}),
    ]
    
    retriever.index_documents(docs)
    
    # Query with Turkish uppercase mapping test
    results = await retriever.retrieve("ŞEKER PANCARI", limit=1)
    
    assert len(results) == 1
    assert results[0].metadata["id"] == 1
    assert results[0].metadata["score"] > 0.0


# ==========================================
# RRF Fusion Tests
# ==========================================
def test_reciprocal_rank_fusion():
    doc1 = Document(page_content="Doc A", metadata={"id": "A"})
    doc2 = Document(page_content="Doc B", metadata={"id": "B"})
    doc3 = Document(page_content="Doc C", metadata={"id": "C"})

    # Dense Rank: A (1), B (2)
    # Sparse Rank: C (1), A (2)
    dense_results = [doc1, doc2]
    sparse_results = [doc3, doc1]

    fused = reciprocal_rank_fusion([dense_results, sparse_results], k=60)
    
    # RRF Score formula: 1 / (60 + Rank)
    # Doc A scores: 1/(60+1) + 1/(60+2) = 1/61 + 1/62 = 0.01639 + 0.01612 = 0.03251
    # Doc B scores: 1/(60+2) = 1/62 = 0.01612
    # Doc C scores: 1/(60+1) = 1/61 = 0.01639
    
    # So Doc A should be rank 1, Doc C rank 2, Doc B rank 3.
    assert len(fused) == 3
    assert fused[0].page_content == "Doc A"
    assert fused[1].page_content == "Doc C"
    assert fused[2].page_content == "Doc B"


# ==========================================
# Hybrid Retriever Tests
# ==========================================
@pytest.mark.asyncio
async def test_hybrid_retriever():
    mock_vector_store = AsyncMock(spec=BaseVectorStore)
    mock_hit = {"text": "Hybrid search result", "score": 0.90, "metadata": {"source": "manual"}}
    mock_vector_store.hybrid_search.return_value = [mock_hit]

    mock_embeddings = MagicMock(spec=BaseEmbeddingsClient)
    mock_embeddings.embed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])

    hybrid = HybridRetriever(
        vector_store=mock_vector_store,
        embeddings_client=mock_embeddings,
        collection_name="docs",
        sparse_vocab_path="nonexistent_vocab.json"
    )

    results = await hybrid.retrieve("Query test", limit=1)

    assert len(results) == 1
    assert results[0].page_content == "Hybrid search result"
    assert results[0].metadata["score"] == 0.90
    mock_vector_store.hybrid_search.assert_called_once()


# LLMReranker was removed: reranking 3 results out of a corpus this small, on
# the critical path of the ~90s draft latency budget, was never where the
# quality was -- see the implementation plan's Phase 8 notes.
#
# The cross-encoder reranker below (Workstream J7) is a different thing
# entirely, not a resurrection of the removed LLMReranker: a small local
# sentence-transformers model scoring (query, candidate) pairs directly, no
# LLM structured-output call, no ~90s critical-path budget -- see
# app.ai.retrieval.reranker's own module docstring.


def _mock_reranker(rerank_side_effect=None) -> MagicMock:
    reranker = MagicMock(spec=BaseReranker)
    reranker.rerank = AsyncMock(side_effect=rerank_side_effect)
    return reranker


def _enabled_rerank_policy(candidate_count: int = 3):
    policy = get_policy()
    return replace(
        policy, rerank=replace(policy.rerank, enabled=True, candidate_count=candidate_count)
    )


@pytest.mark.asyncio
async def test_reranker_is_never_consulted_when_rerank_policy_disabled():
    """RerankPolicy.enabled=False (an emergency-rollback override of the
    production default -- see that policy's own docstring) -- a reranker
    instance being present at all must not change behaviour."""
    mock_vector_store = AsyncMock(spec=BaseVectorStore)
    mock_vector_store.hybrid_search.return_value = [
        {"text": "result", "score": 0.9, "metadata": {}}
    ]
    mock_embeddings = MagicMock(spec=BaseEmbeddingsClient)
    mock_embeddings.embed_query = AsyncMock(return_value=[0.1, 0.2])
    reranker = _mock_reranker()

    hybrid = HybridRetriever(
        vector_store=mock_vector_store,
        embeddings_client=mock_embeddings,
        collection_name="docs",
        reranker=reranker,
    )

    policy = get_policy()
    disabled = replace(policy, rerank=replace(policy.rerank, enabled=False))
    with patch("app.ai.retrieval.hybrid.get_policy", return_value=disabled):
        results = await hybrid.retrieve("query", limit=1)

    assert len(results) == 1
    reranker.rerank.assert_not_called()
    # No widening of the Qdrant fetch either -- disabled must reproduce
    # this class's exact pre-reranker call shape (limit unchanged).
    assert mock_vector_store.hybrid_search.call_args.kwargs["limit"] == 1


@pytest.mark.asyncio
async def test_reranker_widens_the_qdrant_fetch_and_trims_to_limit():
    mock_vector_store = AsyncMock(spec=BaseVectorStore)
    mock_vector_store.hybrid_search.return_value = [
        {"text": f"doc-{i}", "score": 0.5, "metadata": {}} for i in range(3)
    ]
    mock_embeddings = MagicMock(spec=BaseEmbeddingsClient)
    mock_embeddings.embed_query = AsyncMock(return_value=[0.1])

    async def _rerank(query, documents, *, top_k):
        # Reverses the fused order -- proof the reranker's own output, not
        # the fused one, is what retrieve() returns.
        return list(reversed(documents))[:top_k]

    reranker = _mock_reranker(rerank_side_effect=_rerank)
    hybrid = HybridRetriever(
        vector_store=mock_vector_store,
        embeddings_client=mock_embeddings,
        collection_name="docs",
        reranker=reranker,
    )

    with patch(
        "app.ai.retrieval.hybrid.get_policy", return_value=_enabled_rerank_policy()
    ):
        results = await hybrid.retrieve("query", limit=1)

    # candidate_count=3 (via _enabled_rerank_policy) > limit=1 -> Qdrant
    # fetched with the wider candidate pool, not just `limit`.
    assert mock_vector_store.hybrid_search.call_args.kwargs["limit"] == 3
    reranker.rerank.assert_awaited_once()
    assert [doc.page_content for doc in results] == ["doc-2"]


@pytest.mark.asyncio
async def test_reranker_failure_degrades_to_the_fused_order_truncated():
    """CrossEncoderReranker.rerank() itself never raises (see test_
    reranker.py) -- this proves HybridRetriever.retrieve() is safe even if
    some *other* BaseReranker implementation does."""
    mock_vector_store = AsyncMock(spec=BaseVectorStore)
    mock_vector_store.hybrid_search.return_value = [
        {"text": f"doc-{i}", "score": 0.5, "metadata": {}} for i in range(3)
    ]
    mock_embeddings = MagicMock(spec=BaseEmbeddingsClient)
    mock_embeddings.embed_query = AsyncMock(return_value=[0.1])
    reranker = _mock_reranker(rerank_side_effect=RuntimeError("reranker exploded"))

    hybrid = HybridRetriever(
        vector_store=mock_vector_store,
        embeddings_client=mock_embeddings,
        collection_name="docs",
        reranker=reranker,
    )

    with patch(
        "app.ai.retrieval.hybrid.get_policy", return_value=_enabled_rerank_policy()
    ):
        results = await hybrid.retrieve("query", limit=1)

    # HybridRetriever's own broad except (around the whole method) catches
    # the reranker's failure too -- retrieve() degrades to [], the same
    # "never fail the caller" contract it already has for a Qdrant/
    # embeddings failure, not a partial/reordered result.
    assert results == []
