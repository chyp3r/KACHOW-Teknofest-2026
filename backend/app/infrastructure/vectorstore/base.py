from abc import ABC, abstractmethod
from typing import Any, Dict, List

from app.ai.embeddings.service import EmbeddedChunk


class BaseVectorStore(ABC):
    """Abstract Base Class for Vector Database interactions."""

    @abstractmethod
    async def create_collection(
        self, collection_name: str, vector_size: int, distance: str = "Cosine"
    ) -> bool:
        """Create a new collection in the vector database.

        Args:
            collection_name: The name of the collection.
            vector_size: Dimensionality of the vectors.
            distance: Distance metric (e.g. "Cosine", "Euclidean", "Dot").
        """
        pass

    @abstractmethod
    async def upsert_documents(
        self, collection_name: str, chunks: List[EmbeddedChunk]
    ) -> bool:
        """Insert or update embedded chunks in a collection.

        Args:
            collection_name: The name of the collection.
            chunks: List of EmbeddedChunk containing texts, vectors, and metadata.
        """
        pass

    @abstractmethod
    async def similarity_search(
        self, collection_name: str, query_vector: List[float], limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for similar vectors in a collection.

        Args:
            collection_name: The name of the collection.
            query_vector: The query embedding vector.
            limit: Maximum number of results to return.

        Returns:
            A list of dictionary objects, each representing a hit (payload, score, id).
        """
        pass

    @abstractmethod
    async def delete_collection(self, collection_name: str) -> bool:
        """Delete a collection from the vector database.

        Args:
            collection_name: The name of the collection to delete.
        """
        pass

