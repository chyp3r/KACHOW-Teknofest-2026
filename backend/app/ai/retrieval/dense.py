import logging
from typing import List

from langchain_core.documents import Document

from app.ai.embeddings.models import BaseEmbeddingsClient
from app.infrastructure.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)


class DenseRetriever:
    """Sorgu embedding'lerini kullanarak Qdrant vektör veritabanında

    anlamsal benzerlik araması yapan retriever.
    """

    def __init__(
        self,
        vector_store: BaseVectorStore,
        embeddings_client: BaseEmbeddingsClient,
        collection_name: str = "documents",
    ):
        """Dense Retriever'ı başlat.

        Args:
            vector_store: BaseVectorStore istemcisi (ör. QdrantStore).
            embeddings_client: Sorgu vektörünü üretecek BaseEmbeddingsClient.
            collection_name: Aranacak Qdrant koleksiyon adı.
        """
        self.vector_store = vector_store
        self.embeddings_client = embeddings_client
        self.collection_name = collection_name
        logger.info(
            f"Initialized DenseRetriever for collection: {collection_name}"
        )

    async def retrieve(self, query: str, limit: int = 5) -> List[Document]:
        """Anlamsal arama yap ve LangChain Document nesnelerinden oluşan bir liste döndür.

        Args:
            query: Kullanıcının sorusu veya arama sorgusu.
            limit: Getirilecek maksimum belge sayısı.
        """
        if not query.strip():
            return []

        try:
            # 1. Sorguyu embed et
            query_vector = await self.embeddings_client.embed_query(query)

            # 2. Qdrant'ta ara
            hits = await self.vector_store.similarity_search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
            )

            # 3. Sonuçları LangChain Document nesnelerine dönüştür
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
