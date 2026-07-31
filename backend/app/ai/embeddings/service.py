import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.ai.embeddings.chunking.base import BaseChunker
from app.ai.embeddings.models import BaseEmbeddingsClient

logger = logging.getLogger(__name__)


class EmbeddedChunk(BaseModel):
    """Pydantic model representing a single chunk that has been split and embedded."""

    text: str
    vector: List[float]
    metadata: Dict[str, Any]
    sparse_vector: Optional[Dict[str, Any]] = None



class EmbeddingService:
    """Central service orchestrating document splitting and embedding vector generation."""

    def __init__(self, embeddings_client: BaseEmbeddingsClient):
        """Initialize the Embedding Service.

        Args:
            embeddings_client: An instance of BaseEmbeddingsClient.
        """
        self.embeddings_client = embeddings_client
        logger.info("Initialized EmbeddingService successfully.")

    async def process_text(
        self, text: str, chunker: BaseChunker, **kwargs: Any
    ) -> List[EmbeddedChunk]:
        """Split text into chunks and generate embedding vectors for each chunk.

        Args:
            text: The raw input document text.
            chunker: The Chunker strategy (Character, Recursive, Semantic, Agentic).
            **kwargs: Extra parameters to pass to the chunker's split_text method.

        Returns:
            A list of EmbeddedChunk objects.
        """
        if not text.strip():
            return []

        logger.info(
            f"EmbeddingService processing text (length={len(text)}) using chunker [{chunker.__class__.__name__}]..."
        )

        # 1. Split text into documents using the chunker strategy
        docs = await chunker.split_text(text, **kwargs)

        if not docs:
            logger.warning("Chunker returned 0 chunks.")
            return []

        # 2. Extract content from documents
        chunk_texts = [doc.page_content for doc in docs]

        # 3. Generate embedding vectors for all chunks in a batch
        logger.info(f"Generating embeddings for {len(chunk_texts)} chunks...")
        vectors = await self.embeddings_client.embed_documents(chunk_texts)

        # 4. Construct response objects
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
