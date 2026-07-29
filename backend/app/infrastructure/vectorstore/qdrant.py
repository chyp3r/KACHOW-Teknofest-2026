import logging
import uuid
from typing import Any, Dict, List

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.ai.embeddings.service import EmbeddedChunk
from app.infrastructure.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)


class QdrantStore(BaseVectorStore):
    """Qdrant client implementation of BaseVectorStore for vector storage and search."""

    def __init__(self, qdrant_url: str):
        """Initialize Qdrant Store client.

        Args:
            qdrant_url: Endpoint URL of Qdrant DB (e.g. "http://localhost:6333").
        """
        self.qdrant_url = qdrant_url
        self.client = AsyncQdrantClient(url=qdrant_url)
        logger.info(f"Initialized AsyncQdrantClient targeting: {qdrant_url}")

    async def create_collection(
        self, collection_name: str, vector_size: int, distance: str = "Cosine"
    ) -> bool:
        """Create Qdrant collection if it does not already exist."""
        # Map string distance metric to Qdrant models.Distance enum
        dist_enum = models.Distance.COSINE
        dist_lower = distance.lower()
        if dist_lower == "euclidean":
            dist_enum = models.Distance.EUCLID
        elif dist_lower == "dot":
            dist_enum = models.Distance.DOT

        try:
            # Check if collection exists
            exists = await self.client.collection_exists(collection_name)
            if exists:
                logger.info(
                    f"Collection '{collection_name}' already exists in Qdrant."
                )
                return True

            # Create new collection
            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size, distance=dist_enum
                ),
            )
            logger.info(
                f"Successfully created Qdrant collection: '{collection_name}'"
            )
            return True
        except Exception as e:
            logger.error(
                f"Qdrant create_collection failed for '{collection_name}': {e}",
                exc_info=True,
            )
            return False

    async def upsert_documents(
        self, collection_name: str, chunks: List[EmbeddedChunk]
    ) -> bool:
        """Upsert embedded chunks into Qdrant collection."""
        if not chunks:
            return True

        points = []
        for chunk in chunks:
            point_id = str(uuid.uuid4())
            # Save raw text inside payload along with any metadata keys
            payload = {"text": chunk.text, **chunk.metadata}
            points.append(
                models.PointStruct(
                    id=point_id, vector=chunk.vector, payload=payload
                )
            )

        try:
            await self.client.upsert(
                collection_name=collection_name, points=points
            )
            logger.debug(
                f"Upserted {len(chunks)} chunks to collection '{collection_name}'."
            )
            return True
        except Exception as e:
            logger.error(
                f"Qdrant upsert failed for collection '{collection_name}': {e}",
                exc_info=True,
            )
            return False

    async def similarity_search(
        self, collection_name: str, query_vector: List[float], limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search similar vectors in Qdrant collection and return normalized payload objects."""
        try:
            results = await self.client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=limit,
            )

            hits = []
            for hit in results:
                payload = hit.payload or {}
                # Pop out the raw text key
                text = payload.pop("text", "")
                hits.append(
                    {"text": text, "score": hit.score, "metadata": payload}
                )
            return hits
        except Exception as e:
            logger.error(
                f"Qdrant similarity_search failed in '{collection_name}': {e}",
                exc_info=True,
            )
            return []
