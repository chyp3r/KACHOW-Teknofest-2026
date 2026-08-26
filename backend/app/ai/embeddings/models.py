import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from langchain_ollama import OllamaEmbeddings
from langchain_openai import OpenAIEmbeddings

from app.core.config import settings

logger = logging.getLogger(__name__)


class BaseEmbeddingsClient(ABC):
    """Tüm embedding istemcileri için soyut temel sınıf."""

    @abstractmethod
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Bir belge metni listesi için embedding vektörleri üretir."""
        pass

    @abstractmethod
    async def embed_query(self, text: str) -> List[float]:
        """Tek bir sorgu metni için embedding vektörü üretir."""
        pass


class OllamaEmbeddingsClient(BaseEmbeddingsClient):
    """Embedding üretimi için Ollama uygulaması."""

    def __init__(self, base_url: str, model: str):
        """Ollama Embeddings istemcisini başlatır.

        Args:
            base_url: Ollama servisinin çalıştığı URL.
            model: Embedding modelinin adı (ör. "nomic-embed-text:latest").
        """
        self.base_url = base_url
        self.model_name = model
        self._embeddings = OllamaEmbeddings(base_url=base_url, model=model)
        logger.info(
            f"Initialized OllamaEmbeddingsClient with base_url={base_url}, model={model}"
        )

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Belgeler için embedding'leri asenkron olarak üretir."""
        try:
            return await self._embeddings.aembed_documents(texts)
        except Exception as e:
            logger.error(
                f"OllamaEmbeddingsClient failed to embed documents: {e}",
                exc_info=True,
            )
            raise

    async def embed_query(self, text: str) -> List[float]:
        """Sorgu için embedding'i asenkron olarak üretir."""
        try:
            return await self._embeddings.aembed_query(text)
        except Exception as e:
            logger.error(
                f"OllamaEmbeddingsClient failed to embed query: {e}",
                exc_info=True,
            )
            raise


class EvrenEmbeddingsClient(BaseEmbeddingsClient):
    """Embedding üretimi için Evren (TEKNOFEST barındırmalı çıkarım) uygulaması."""

    def __init__(self, base_url: str, api_key: Optional[str], model: str):
        """Evren Embeddings istemcisini başlatır.

        Args:
            base_url: Evren'in OpenAI uyumlu API kök adresi.
            api_key: Takım bearer token'ı.
            model: Embedding modelinin adı (ör. "bge-m3-embed").
        """
        self.base_url = base_url
        self.model_name = model
        self._embeddings = OpenAIEmbeddings(base_url=base_url, api_key=api_key, model=model)
        logger.info(
            f"Initialized EvrenEmbeddingsClient with base_url={base_url}, model={model}"
        )

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Belgeler için embedding'leri asenkron olarak üretir."""
        try:
            return await self._embeddings.aembed_documents(texts)
        except Exception as e:
            logger.error(
                f"EvrenEmbeddingsClient failed to embed documents: {e}",
                exc_info=True,
            )
            raise

    async def embed_query(self, text: str) -> List[float]:
        """Sorgu için embedding'i asenkron olarak üretir."""
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
    """Uygun embedding istemcisini döndüren factory fonksiyonu.

    Args:
        provider: Sağlayıcı tipi ("ollama" veya "evren"). Varsayılan olarak
            ``settings.LOCAL_MODE``'un çözümlediği sağlayıcı kullanılır.
        base_url: Base URL geçersiz kılma.
        model: Model adı geçersiz kılma.
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
