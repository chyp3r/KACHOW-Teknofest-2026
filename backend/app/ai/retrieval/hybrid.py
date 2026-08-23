import os
import logging
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from app.ai.embeddings.models import BaseEmbeddingsClient
from app.ai.policy import get_policy
from app.ai.retrieval.reranker import BaseReranker
from app.ai.retrieval.sparse_encoder import SparseBM25Encoder
from app.infrastructure.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)


class HybridRetriever:
    """SOTA Hybrid Retriever executing unified dense + sparse vector queries on Qdrant.

    Merges search scores natively inside the Qdrant database using Reciprocal Rank Fusion (RRF).
    """

    def __init__(
        self,
        vector_store: BaseVectorStore,
        embeddings_client: BaseEmbeddingsClient,
        collection_name: str = "documents",
        sparse_vocab_path: str = "",
        reranker: Optional[BaseReranker] = None,
    ):
        """Initialize Native Hybrid Retriever.

        Args:
            vector_store: BaseVectorStore client (e.g. QdrantStore).
            embeddings_client: BaseEmbeddingsClient to generate query vector.
            collection_name: Qdrant collection name to search.
            sparse_vocab_path: Path to the fitted sparse vocab JSON file.
            reranker: Optional cross-encoder second pass (see
                ``app.ai.retrieval.reranker``, ``RerankPolicy``). ``None``
                (the default) reproduces this class's exact pre-reranker
                behaviour -- ``retrieve`` never widens its Qdrant fetch
                past ``limit`` and returns the RRF-fused order unchanged.
        """
        self.vector_store = vector_store
        self.embeddings_client = embeddings_client
        self.collection_name = collection_name
        self.sparse_vocab_path = sparse_vocab_path
        self.reranker = reranker

        self.sparse_encoder = SparseBM25Encoder()
        if sparse_vocab_path and os.path.exists(sparse_vocab_path):
            self.sparse_encoder.load(sparse_vocab_path)
        else:
            logger.warning(
                f"Sparse vocabulary file not found at {sparse_vocab_path}. "
                "Sparse query weights will default to 1.0."
            )

        logger.info(
            f"Initialized HybridRetriever targeting collection '{collection_name}'"
        )

    async def retrieve(
        self,
        query: str,
        limit: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Perform semantic and keyword search simultaneously on Qdrant, returning RRF-fused results.

        Args:
            query: User's question or search query.
            limit: Maximum documents to retrieve.
            filter_dict: Optional payload filter, forwarded as-is to
                ``BaseVectorStore.hybrid_search`` (see its
                ``_build_qdrant_filter`` for the accepted shape).
        """
        if not query.strip():
            return []

        try:
            # 0. Reranking (if wired) needs a wider candidate pool than
            # `limit` to actually have something to reorder -- fetch
            # `RerankPolicy.candidate_count` from Qdrant instead, and trim
            # to `limit` only after the rerank pass below. `max(...)`
            # guards a caller passing a `limit` larger than the pool size.
            policy = get_policy().rerank
            fetch_limit = (
                max(limit, policy.candidate_count)
                if self.reranker is not None and policy.enabled
                else limit
            )

            # 1. Embed dense query
            query_vector = await self.embeddings_client.embed_query(query)

            # 2. Encode sparse query (BM25)
            sparse_indices, sparse_values = self.sparse_encoder.encode_query(query)

            # 3. Query Qdrant with native hybrid search
            hits = await self.vector_store.hybrid_search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                sparse_indices=sparse_indices,
                sparse_values=sparse_values,
                limit=fetch_limit,
                filter_dict=filter_dict,
            )

            # 4. Format hits into LangChain Document objects
            documents = []
            for hit in hits:
                metadata = hit.get("metadata", {}).copy()
                metadata["score"] = hit.get("score", 0.0)
                documents.append(
                    Document(
                        page_content=hit.get("text", ""), metadata=metadata
                    )
                )

            logger.info(
                f"HybridRetriever found {len(documents)} results natively from Qdrant."
            )

            # 5. Cross-encoder second pass, if enabled -- reorders the wider
            # candidate pool by (query, candidate) relevance and trims to
            # the caller's actual `limit`. Never raises: CrossEncoderReranker.
            # rerank() degrades to the fused (pre-rerank) order on any
            # failure, so a reranker outage narrows this back to `limit`
            # exactly as if `fetch_limit == limit` had been requested.
            if self.reranker is not None and policy.enabled and len(documents) > limit:
                documents = await self.reranker.rerank(query, documents, top_k=limit)
            else:
                documents = documents[:limit]

            return documents

        except Exception as e:
            logger.error(
                f"HybridRetriever search failed for query '{query}': {e}",
                exc_info=True,
            )
            return []
