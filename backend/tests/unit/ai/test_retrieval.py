import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.documents import Document

from app.ai.retrieval import (
    DenseRetriever,
    BM25Retriever,
    reciprocal_rank_fusion,
    HybridRetriever,
)
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
