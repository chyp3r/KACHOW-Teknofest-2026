import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from app.ai.llms.base import BaseLLMClient
from app.core.config import settings

logger = logging.getLogger(__name__)


class OllamaClient(BaseLLMClient):
    """Client for interacting with a local Ollama instance using LangChain.

    Two properties matter for local inference and both were previously missing:

    1. ``num_ctx`` is set on every call. Ollama's default context window is 2048
       tokens and it truncates *from the beginning* without warning -- which
       silently deletes the system prompt or the document header. Setting this
       per-node (as the code used to) leaves every other node broken.
    2. ``ChatOllama`` instances are cached. Building one per call discarded the
       underlying HTTP connection pool on every request.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.7,
        reasoning: bool = False,
        max_tokens: int = 4096,
        num_ctx: int | None = None,
        keep_alive: str | None = None,
    ):
        """Initialize the Ollama client.

        Args:
            base_url: The URL where the local Ollama instance is running.
            model: The name of the model to use.
            temperature: Default temperature for generation.
            reasoning: Whether the model should use its thinking mode.
            max_tokens: Default maximum number of generated tokens.
            num_ctx: Context window size. Defaults to ``settings.OLLAMA_NUM_CTX``.
            keep_alive: How long Ollama keeps the model resident between calls.
        """
        self.base_url = base_url
        self.model_name = model
        self.temperature = temperature
        self.reasoning = reasoning
        self.max_tokens = max_tokens
        self.num_ctx = num_ctx if num_ctx is not None else settings.OLLAMA_NUM_CTX
        self.keep_alive = (
            keep_alive if keep_alive is not None else settings.OLLAMA_KEEP_ALIVE
        )
        self._client_cache: dict[tuple, ChatOllama] = {}
        logger.info(
            "Initialized OllamaClient base_url=%s model=%s temperature=%s "
            "reasoning=%s max_tokens=%s num_ctx=%s keep_alive=%s",
            base_url,
            model,
            temperature,
            reasoning,
            max_tokens,
            self.num_ctx,
            self.keep_alive,
        )

    def _build_client(
        self,
        temperature: float,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ChatOllama:
        """Return a configured Ollama client, reusing one per parameter set.

        Args:
            temperature: Sampling temperature for this call.
            max_tokens: Generation budget, falling back to the client default.
            **kwargs: Extra ChatOllama options. ``reasoning``, ``num_predict``
                and ``num_ctx`` are consumed here; anything else is forwarded.

        Returns:
            A cached or newly built ``ChatOllama``.
        """
        reasoning = kwargs.pop("reasoning", self.reasoning)
        num_predict = kwargs.pop(
            "num_predict",
            max_tokens if max_tokens is not None else self.max_tokens,
        )
        num_ctx = kwargs.pop("num_ctx", self.num_ctx)

        # Only hashable extras may participate in the cache key; anything else
        # forces a fresh client rather than silently sharing the wrong config.
        try:
            extra_key = tuple(sorted(kwargs.items()))
            cacheable = True
        except TypeError:
            extra_key = ()
            cacheable = False

        cache_key = (temperature, num_predict, num_ctx, reasoning, extra_key)
        if cacheable and cache_key in self._client_cache:
            return self._client_cache[cache_key]

        client = ChatOllama(
            base_url=self.base_url,
            model=self.model_name,
            temperature=temperature,
            reasoning=reasoning,
            num_predict=num_predict,
            num_ctx=num_ctx,
            keep_alive=self.keep_alive,
            **kwargs,
        )
        if cacheable:
            self._client_cache[cache_key] = client
        return client

    def _convert_messages(self, messages: list[dict[str, str]]) -> list[BaseMessage]:
        """Convert standard message dicts to LangChain Message objects."""
        lc_messages: list[BaseMessage] = []
        for msg in messages:
            role = msg.get("role", "user").lower()
            content = msg.get("content", "")
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role in ("assistant", "ai"):
                lc_messages.append(AIMessage(content=content))
            else:
                logger.warning(
                    "Unknown message role: %s, defaulting to HumanMessage", role
                )
                lc_messages.append(HumanMessage(content=content))

        # A chat model given only a system turn has nothing to respond to and
        # some Ollama templates emit an empty completion. Guarantee a user turn.
        if lc_messages and all(isinstance(m, SystemMessage) for m in lc_messages):
            lc_messages.append(HumanMessage(content="Yönergeye göre yanıt üret."))
        return lc_messages

    async def generate(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        """Generate response from a list of messages using local Ollama."""
        temp = temperature if temperature is not None else self.temperature

        client = self._build_client(temp, max_tokens, **kwargs)
        lc_messages = self._convert_messages(messages)

        started = time.perf_counter()
        try:
            response = await client.ainvoke(lc_messages)
        except Exception:
            logger.exception("Error generating response from Ollama")
            raise

        logger.info(
            "Ollama generate model=%s took=%.2fs",
            self.model_name,
            time.perf_counter() - started,
        )
        return str(response.content)

    async def stream(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream response chunk-by-chunk using local Ollama."""
        temp = temperature if temperature is not None else self.temperature

        client = self._build_client(temp, max_tokens, **kwargs)
        lc_messages = self._convert_messages(messages)

        try:
            async for chunk in client.astream(lc_messages):
                text = str(chunk.content)
                if text:
                    yield text
        except Exception:
            logger.exception("Error streaming response from Ollama")
            raise

    async def generate_structured(
        self,
        messages: list[dict[str, str]],
        response_model: Any,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """Generate structured output validated against a Pydantic model.

        Thinking mode is forced off: reasoning tokens are emitted before the JSON
        body, consume the ``num_predict`` budget and routinely truncate the
        object being validated.

        ``method="function_calling"`` is pinned rather than the library's
        ``"json_schema"`` default. The latter maps to Ollama's native
        ``format=<schema>`` grammar-constrained decoding -- but that path is
        silently a no-op for models running on a custom Ollama
        renderer/parser engine (e.g. ``qwen3.5``, whose ``ollama show``
        template is a bare ``{{ .Prompt }}`` passthrough): verified directly
        against the Ollama API that ``format`` (both the plain ``"json"``
        string and a full JSON-schema object) was ignored outright, while a
        request built with these same models' ``tools`` array was honoured
        exactly, including nested/optional fields and enum values. Native
        tool-calling is the structured-output path this engine actually
        implements.
        """
        temp = temperature if temperature is not None else self.temperature
        max_tokens = kwargs.pop("max_tokens", None)
        kwargs.setdefault("reasoning", False)
        client = self._build_client(temp, max_tokens, **kwargs)

        lc_messages = self._convert_messages(messages)

        started = time.perf_counter()
        try:
            structured_llm = client.with_structured_output(
                response_model, method="function_calling"
            )
            result = await structured_llm.ainvoke(lc_messages)
        except Exception:
            logger.exception("Error generating structured response from Ollama")
            raise

        logger.info(
            "Ollama structured model=%s schema=%s took=%.2fs",
            self.model_name,
            getattr(response_model, "__name__", response_model),
            time.perf_counter() - started,
        )
        return result

    async def warm_up(self) -> bool:
        """Load the model into memory so the first real request is not cold.

        Returns:
            True when the model responded, False when Ollama was unreachable.
        """
        try:
            await self._build_client(0.0, 1).ainvoke(
                [HumanMessage(content="ping")]
            )
            logger.info("Warmed up Ollama model '%s'.", self.model_name)
            return True
        except Exception as exc:
            logger.warning(
                "Could not warm up Ollama model '%s': %s", self.model_name, exc
            )
            return False
