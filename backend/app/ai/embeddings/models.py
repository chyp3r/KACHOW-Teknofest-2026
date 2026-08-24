import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from langchain_ollama import OllamaEmbeddings
from langchain_openai import OpenAIEmbeddings

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

    def __init__(self, base_url: str, model: str):
        """Initialize Ollama Embeddings client.

        Args:
            base_url: The URL where the Ollama service is running.
            model: The name of the embedding model (e.g. "nomic-embed-text:latest").
        """
        self.base_url = base_url
        self.model_name = model
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
            return await self._embeddings.aembed_query(text)
        except Exception as e:
            logger.error(
                f"OllamaEmbeddingsClient failed to embed query: {e}",
                exc_info=True,
            )
            raise


class EvrenEmbeddingsClient(BaseEmbeddingsClient):
    """Evren (TEKNOFEST hosted inference) implementation for embedding generation."""

    def __init__(self, base_url: str, api_key: Optional[str], model: str):
        """Initialize Evren Embeddings client.

        Args:
            base_url: Evren's OpenAI-compatible API root.
            api_key: Team bearer token.
            model: The name of the embedding model (e.g. "bge-m3-embed").
        """
        self.base_url = base_url
        self.model_name = model
        self._embeddings = OpenAIEmbeddings(base_url=base_url, api_key=api_key, model=model)
        logger.info(
            f"Initialized EvrenEmbeddingsClient with base_url={base_url}, model={model}"
        )

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for documents asynchronously."""
        try:
            return await self._embeddings.aembed_documents(texts)
        except Exception as e:
            logger.error(
                f"EvrenEmbeddingsClient failed to embed documents: {e}",
                exc_info=True,
            )
            raise

    async def embed_query(self, text: str) -> List[float]:
        """Generate embedding for query asynchronously."""
        try:
            return await self._embeddings.aembed_query(text)
        except Exception as e:
            logger.error(
                f"EvrenEmbeddingsClient failed to embed query: {e}",
                exc_info=True,
            )
            raise


def get_embeddings_client(
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> BaseEmbeddingsClient:
    """Factory function to get the appropriate embeddings client.

    Args:
        provider: Provider type ("ollama" or "evren"). Defaults to
            ``settings.LOCAL_MODE``'s resolved provider.
        base_url: Base URL override.
        model: Model name override.
    """
    provider_lower = (
        provider.lower() if provider else ("ollama" if settings.LOCAL_MODE else "evren")
    )

    if provider_lower == "ollama":
        url = base_url or settings.OLLAMA_BASE_URL
        model_name = model or settings.OLLAMA_EMBEDDING_MODEL
        return OllamaEmbeddingsClient(base_url=url, model=model_name)
    elif provider_lower == "evren":
        url = base_url or settings.EVREN_BASE_URL
        model_name = model or settings.EVREN_EMBED_MODEL
        return EvrenEmbeddingsClient(
            base_url=url, api_key=settings.EVREN_API_KEY, model=model_name
        )
    else:
        raise ValueError(f"Unsupported embeddings provider: {provider}")
