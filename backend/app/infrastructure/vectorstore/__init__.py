from app.core.config import settings
from app.infrastructure.vectorstore.base import BaseVectorStore
from app.infrastructure.vectorstore.qdrant import QdrantStore

# Lazy singleton vectorstore instance
_vector_store = None


def get_vector_store() -> BaseVectorStore:
    """Retrieve the global configured vector store instance (Qdrant).

    Targets the local Docker-Compose Qdrant when ``settings.LOCAL_MODE`` is
    True, or Evren's dedicated hosted cluster otherwise -- a wholly separate
    server, so the two modes' collections never mix even though their
    embedding vectors have different dimensions (nomic-embed-text vs.
    bge-m3-embed).
    """
    global _vector_store
    if _vector_store is None:
        if settings.LOCAL_MODE:
            _vector_store = QdrantStore(qdrant_url=settings.QDRANT_URL)
        else:
            _vector_store = QdrantStore(
                qdrant_url=settings.EVREN_QDRANT_URL,
                api_key=settings.EVREN_QDRANT_API_KEY,
            )
    return _vector_store


__all__ = ["BaseVectorStore", "QdrantStore", "get_vector_store"]
