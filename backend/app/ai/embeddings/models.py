import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from langchain_ollama import OllamaEmbeddings

from app.core.config import settings

logger = logging.getLogger(__name__)


class BaseEmbeddingsClient(ABC):
    """Abstract base class for all embedding clients."""

    @abstractmethod
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for a list of document texts."""
        pass

    @abstractmethod
    async def embed_query(self, text: str) -> List[float]:
        """Generate embedding vector for a single query text."""
        pass


class OllamaEmbeddingsClient(BaseEmbeddingsClient):
    """Ollama implementation for embedding generation."""

    def __init__(self, base_url: str, model: str, instruct_prefix: str = ""):
        """Initialize Ollama Embeddings client.

        Args:
            base_url: The URL where the Ollama service is running.
            model: The name of the embedding model (e.g. "nomic-embed-text:latest").
            instruct_prefix: Prepended to every ``embed_query`` call only,
                never ``embed_documents`` -- some models (e.g.
                harrier-oss-v1-0.6b, see ``settings.
                OLLAMA_EMBEDDING_INSTRUCT_PREFIX``'s own docstring) are
                trained with an asymmetric query/passage instruction
                format and measurably degrade without it. Empty (the
                default) reproduces this class's exact pre-existing
                behaviour for a model that wants no prefix at all.
        """
        self.base_url = base_url
        self.model_name = model
        self.instruct_prefix = instruct_prefix
        self._embeddings = OllamaEmbeddings(base_url=base_url, model=model)
        logger.info(
            f"Initialized OllamaEmbeddingsClient with base_url={base_url}, model={model}"
        )

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for documents asynchronously."""
        try:
            return await self._embeddings.aembed_documents(texts)
        except Exception as e:
            logger.error(
                f"OllamaEmbeddingsClient failed to embed documents: {e}",
                exc_info=True,
            )
            raise

    async def embed_query(self, text: str) -> List[float]:
        """Generate embedding for query asynchronously."""
        try:
            return await self._embeddings.aembed_query(self.instruct_prefix + text)
        except Exception as e:
            logger.error(
                f"OllamaEmbeddingsClient failed to embed query: {e}",
                exc_info=True,
            )
            raise


def get_embeddings_client(
    provider: str = "ollama",
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> BaseEmbeddingsClient:
    """Factory function to get the appropriate embeddings client.

    Args:
        provider: Provider type (default: "ollama").
        base_url: Base URL override.
        model: Model name override.
    """
    provider_lower = provider.lower()

    if provider_lower == "ollama":
        url = base_url or settings.OLLAMA_BASE_URL
        model_name = model or settings.OLLAMA_EMBEDDING_MODEL
        return OllamaEmbeddingsClient(
            base_url=url,
            model=model_name,
            instruct_prefix=settings.OLLAMA_EMBEDDING_INSTRUCT_PREFIX,
        )
    else:
        raise ValueError(f"Unsupported embeddings provider: {provider}")
