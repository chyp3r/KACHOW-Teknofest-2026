import os
import logging
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from app.ai.embeddings.models import BaseEmbeddingsClient
from app.ai.retrieval.sparse_encoder import SparseBM25Encoder
from app.infrastructure.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)


class HybridRetriever:
    """Qdrant üzerinde birleşik dense + sparse vektör sorguları yürüten hibrit retriever.

    Arama skorlarını Qdrant veritabanı içinde, Reciprocal Rank Fusion (RRF)
    kullanarak native olarak birleştirir.
    """

    def __init__(
        self,
        vector_store: BaseVectorStore,
        embeddings_client: BaseEmbeddingsClient,
        collection_name: str = "documents",
        sparse_vocab_path: str = "",
    ):
        """Native Hybrid Retriever'ı başlat.

        Args:
            vector_store: BaseVectorStore istemcisi (ör. QdrantStore).
            embeddings_client: Sorgu vektörünü üretecek BaseEmbeddingsClient.
            collection_name: Aranacak Qdrant koleksiyon adı.
            sparse_vocab_path: Fit edilmiş sparse vocab JSON dosyasının yolu.
        """
        self.vector_store = vector_store
        self.embeddings_client = embeddings_client
        self.collection_name = collection_name
        self.sparse_vocab_path = sparse_vocab_path

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
        """Qdrant'ta eş zamanlı anlamsal ve anahtar kelime araması yap, RRF ile birleştirilmiş sonuçları döndür.

        Args:
            query: Kullanıcının sorusu veya arama sorgusu.
            limit: Getirilecek maksimum belge sayısı.
            filter_dict: İsteğe bağlı payload filtresi; olduğu gibi
                ``BaseVectorStore.hybrid_search``'e iletilir (kabul edilen
                şekil için onun ``_build_qdrant_filter``'ına bakın).
        """
        if not query.strip():
            return []

        try:
            # 1. Dense sorguyu embed et
            query_vector = await self.embeddings_client.embed_query(query)

            # 2. Sparse sorguyu kodla (BM25)
            sparse_indices, sparse_values = self.sparse_encoder.encode_query(query)

            # 3. Qdrant'ı native hibrit arama ile sorgula
            hits = await self.vector_store.hybrid_search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                sparse_indices=sparse_indices,
                sparse_values=sparse_values,
                limit=limit,
                filter_dict=filter_dict,
            )

            # 4. Sonuçları LangChain Document nesnelerine dönüştür
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
            return documents

        except Exception as e:
            logger.error(
                f"HybridRetriever search failed for query '{query}': {e}",
                exc_info=True,
            )
            return []
