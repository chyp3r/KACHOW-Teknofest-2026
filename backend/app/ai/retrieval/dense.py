import logging
from typing import List

from langchain_core.documents import Document

from app.ai.embeddings.models import BaseEmbeddingsClient
from app.infrastructure.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)


class DenseRetriever:
    """Retriever that performs semantic similarity search on Qdrant vector database

    using query embeddings.
    """

    def __init__(
        self,
        vector_store: BaseVectorStore,
        embeddings_client: BaseEmbeddingsClient,
        collection_name: str = "documents",
    ):
        """Initialize Dense Retriever.

        Args:
            vector_store: BaseVectorStore client (e.g. QdrantStore).
            embeddings_client: BaseEmbeddingsClient to generate query vector.
            collection_name: Qdrant collection name to search.
        """
        self.vector_store = vector_store
        self.embeddings_client = embeddings_client
        self.collection_name = collection_name
        logger.info(
            f"Initialized DenseRetriever for collection: {collection_name}"
        )

    async def retrieve(self, query: str, limit: int = 5) -> List[Document]:
        """Perform semantic search and return a list of LangChain Document objects.

        Args:
            query: User's question or search query.
            limit: Maximum documents to retrieve.
        """
        if not query.strip():
            return []

        try:
            # 1. Embed query
            query_vector = await self.embeddings_client.embed_query(query)

            # 2. Search Qdrant
            hits = await self.vector_store.similarity_search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
            )

            # 3. Format hits into LangChain Document objects
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
                f"DenseRetriever found {len(documents)} results for query: '{query[:30]}...'"
            )
            return documents

        except Exception as e:
            logger.error(
                f"DenseRetriever search failed for query '{query}': {e}",
                exc_info=True,
            )
            return []
