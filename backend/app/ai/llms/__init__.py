"""LLM client factory.

Two tiers are exposed on purpose. On local hardware the dominant cost is
generated tokens, and most agent decisions in this system (intent, unit routing,
query classification) produce a label plus one sentence. Running those on the
same 9B model as the drafting agent triples the cheap legs of the pipeline for
no accuracy gain.

``get_llm_client()``      -- the drafting/analysis model (quality tier).
``get_fast_llm_client()`` -- small model for short, structured decisions.

Both are cached per process: building a client is cheap but the underlying
connection pool is not, and the graphs are compiled once and reused.
"""

from app.ai.llms.base import BaseLLMClient
from app.core.config import settings
from app.infrastructure.providers.ollama import OllamaClient

_client_cache: dict[tuple, BaseLLMClient] = {}


def get_llm_client(
    provider: str = "ollama",
    base_url: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> BaseLLMClient:
    """Instantiate (or reuse) the configured LLM client.

    Args:
        provider: The name of the LLM provider (currently only "ollama").
        base_url: Optional override for the provider's API URL.
        model: Optional override for the model name.
        temperature: Optional override for the temperature.
        max_tokens: Optional override for the generation budget.

    Returns:
        An instance of BaseLLMClient.

    Raises:
        ValueError: If the provider is not supported.
    """
    provider_lower = provider.lower()
    cache_key = (provider_lower, base_url, model, temperature, max_tokens)
    cached = _client_cache.get(cache_key)
    if cached is not None:
        return cached

    if provider_lower == "ollama":
        client: BaseLLMClient = OllamaClient(
            base_url=base_url or settings.OLLAMA_BASE_URL,
            model=model or settings.OLLAMA_MODEL,
            temperature=(
                temperature if temperature is not None else settings.OLLAMA_TEMPERATURE
            ),
            reasoning=settings.OLLAMA_REASONING,
            max_tokens=(
                max_tokens if max_tokens is not None else settings.OLLAMA_MAX_TOKENS
            ),
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")

    _client_cache[cache_key] = client
    return client


def get_fast_llm_client(provider: str = "ollama") -> BaseLLMClient:
    """Return the small-model client used for short, structured decisions.

    Falls back to the main model when ``OLLAMA_FAST_MODEL`` is unset, so an
    environment that has only pulled one model keeps working unchanged.

    Args:
        provider: The name of the LLM provider.

    Returns:
        An instance of BaseLLMClient.
    """
    if provider.lower() != "ollama" or not settings.OLLAMA_FAST_MODEL:
        return get_llm_client(provider=provider)

    return get_llm_client(
        provider=provider,
        model=settings.OLLAMA_FAST_MODEL,
        temperature=0.0,
        max_tokens=settings.OLLAMA_FAST_MAX_TOKENS,
    )


def iter_cached_clients() -> list[BaseLLMClient]:
    """Return every client built so far, for startup warm-up and diagnostics."""
    return list(_client_cache.values())


__all__ = [
    "BaseLLMClient",
    "OllamaClient",
    "get_fast_llm_client",
    "get_llm_client",
    "iter_cached_clients",
]
