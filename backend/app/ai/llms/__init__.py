from typing import Optional

from app.ai.llms.base import BaseLLMClient
from app.ai.llms.ollama import OllamaClient
from app.core.config import settings


def get_llm_client(
    provider: str = "ollama",
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
) -> BaseLLMClient:
    """Factory function to instantiate and return the configured LLM client.

    Args:
        provider: The name of the LLM provider (default: "ollama").
        base_url: Optional override for the provider's API URL.
        model: Optional override for the model name.
        temperature: Optional override for the temperature.

    Returns:
        An instance of BaseLLMClient.
    """
    provider_lower = provider.lower()

    if provider_lower == "ollama":
        url = base_url or settings.OLLAMA_BASE_URL
        model_name = model or settings.OLLAMA_MODEL
        temp = temperature if temperature is not None else settings.OLLAMA_TEMPERATURE
        return OllamaClient(base_url=url, model=model_name, temperature=temp)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


__all__ = ["BaseLLMClient", "OllamaClient", "get_llm_client"]
