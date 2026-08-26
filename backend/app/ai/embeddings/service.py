import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.ai.embeddings.chunking.base import BaseChunker
from app.ai.embeddings.models import BaseEmbeddingsClient

logger = logging.getLogger(__name__)


class EmbeddedChunk(BaseModel):
    """Bölünmüş ve embedding'i üretilmiş tek bir parçayı temsil eden Pydantic modeli."""

    text: str
    vector: List[float]
    metadata: Dict[str, Any]
    sparse_vector: Optional[Dict[str, Any]] = None



class EmbeddingService:
    """Belge bölme ve embedding vektörü üretimini yöneten merkezi servis."""

    def __init__(self, embeddings_client: BaseEmbeddingsClient):
        """Embedding Servisini başlatır.

        Args:
            embeddings_client: Bir BaseEmbeddingsClient örneği.
        """
        self.embeddings_client = embeddings_client
        logger.info("Initialized EmbeddingService successfully.")

    async def process_text(
        self, text: str, chunker: BaseChunker, **kwargs: Any
    ) -> List[EmbeddedChunk]:
        """Metni parçalara böler ve her parça için embedding vektörü üretir.

        Args:
            text: Ham girdi belge metni.
            chunker: Chunker stratejisi (Character, Recursive, Semantic, Agentic).
            **kwargs: Chunker'ın split_text metoduna geçirilecek ek parametreler.

        Returns:
            EmbeddedChunk nesnelerinden oluşan bir liste.
        """
        if not text.strip():
            return []

        logger.info(
            f"EmbeddingService processing text (length={len(text)}) using chunker [{chunker.__class__.__name__}]..."
        )

        # 1. Chunker stratejisini kullanarak metni belgelere böl
        docs = await chunker.split_text(text, **kwargs)

        if not docs:
            logger.warning("Chunker returned 0 chunks.")
            return []

        # 2. Belgelerden içeriği çıkar
        chunk_texts = [doc.page_content for doc in docs]

        # 3. Tüm parçalar için embedding vektörlerini toplu olarak üret
        logger.info(f"Generating embeddings for {len(chunk_texts)} chunks...")
        vectors = await self.embeddings_client.embed_documents(chunk_texts)

        # 4. Yanıt nesnelerini oluştur
        embedded_chunks = []
        for doc, vector in zip(docs, vectors):
            embedded_chunks.append(
                EmbeddedChunk(
                    text=doc.page_content, vector=vector, metadata=doc.metadata
                )
            )

        logger.info(
            f"EmbeddingService successfully completed. Processed {len(embedded_chunks)} chunks."
        )
        return embedded_chunks
