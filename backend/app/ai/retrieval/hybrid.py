import asyncio
import logging
from typing import List

from langchain_core.documents import Document

from app.ai.retrieval.bm25 import BM25Retriever
from app.ai.retrieval.dense import DenseRetriever
from app.ai.retrieval.fusion import reciprocal_rank_fusion

logger = logging.getLogger(__name__)


class HybridRetriever:
    """SOTA Hybrid Retriever that combines Dense (semantic) and Sparse (BM25 keyword)

    retrievals in parallel, merging them via Reciprocal Rank Fusion (RRF).
    """

    def __init__(
        self,
        dense_retriever: DenseRetriever,
        bm25_retriever: BM25Retriever,
        k: int = 60,
    ):
        """Initialize Hybrid Retriever.

        Args:
            dense_retriever: DenseRetriever instance.
            bm25_retriever: BM25Retriever instance.
            k: Reciprocal Rank Fusion parameter (default: 60).
        """
        self.dense = dense_retriever
        self.bm25 = bm25_retriever
        self.k = k
        logger.info("Initialized HybridRetriever.")

    async def retrieve(self, query: str, limit: int = 5) -> List[Document]:
        """Retrieve documents using both semantic and keyword search in parallel,

        merging them and returning the top candidates.

        Args:
            query: User search query.
            limit: Maximum documents to return.
        """
        if not query.strip():
            return []

        # Request more candidates (e.g. limit * 2) from base retrievers
        # to ensure high-quality coverage during fusion.
        fetch_limit = max(limit * 2, 10)

        # Run retrievals in parallel for optimum speed
        dense_task = self.dense.retrieve(query, limit=fetch_limit)
        bm25_task = self.bm25.retrieve(query, limit=fetch_limit)

        dense_results, bm25_results = await asyncio.gather(
            dense_task, bm25_task
        )

        # Merge results using Reciprocal Rank Fusion
        fused_results = reciprocal_rank_fusion(
            [dense_results, bm25_results], k=self.k
        )

        logger.info(
            f"HybridRetriever unified {len(dense_results)} dense and {len(bm25_results)} sparse "
            f"results into {len(fused_results)} total, returning top {limit}."
        )

        # Return top limit
        return fused_results[:limit]
