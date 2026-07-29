from app.core.config import settings
from app.infrastructure.vectorstore.base import BaseVectorStore
from app.infrastructure.vectorstore.qdrant import QdrantStore

# Lazy singleton vectorstore instance
_vector_store = None


def get_vector_store() -> BaseVectorStore:
    """Retrieve the global configured vector store instance (Qdrant)."""
    global _vector_store
    if _vector_store is None:
        _vector_store = QdrantStore(qdrant_url=settings.QDRANT_URL)
    return _vector_store


__all__ = ["BaseVectorStore", "QdrantStore", "get_vector_store"]
