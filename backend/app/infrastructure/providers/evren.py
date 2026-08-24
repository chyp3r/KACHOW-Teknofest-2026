import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain_openai import ChatOpenAI

from app.ai.llms.base import BaseLLMClient, ToolCallResponse
from app.core.config import settings
from app.infrastructure.providers.message_utils import convert_messages

logger = logging.getLogger(__name__)


class EvrenClient(BaseLLMClient):
    """Client for Evren, the TEKNOFEST-provided hosted inference API.

    OpenAI-compatible (bearer token, ``/v1/chat/completions``), served on
    shared H200 hardware -- the online counterpart to ``OllamaClient``. Same
    method surface, same caching-by-parameter-set shape, same
    ``method="function_calling"`` pin for structured/tool output (Evren's own
    troubleshooting docs confirm the underlying vLLM engine's native
    tool-calling is the reliable structured-output path, same trade Ollama's
    custom-renderer models needed).
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        temperature: float = 0.7,
        reasoning: bool = False,
        max_tokens: int = 4096,
        request_timeout: float | None = None,
    ):
        """Initialize the Evren client.

        Args:
            base_url: Evren's OpenAI-compatible API root, e.g.
                ``https://evren-llmapi.ssyz.org.tr/v1``.
            model: One of Evren's model aliases (e.g. "llm-fast", "llm-large",
                "guard", "router").
            api_key: Team bearer token. Required in practice -- Evren rejects
                unauthenticated requests -- but not validated here so a
                missing key fails at the first real call with Evren's own
                401, not at client construction.
            temperature: Default sampling temperature.
            reasoning: Whether to request thinking mode (``enable_thinking``).
                Evren's own docs discourage this and document a failure mode
                (empty response, ``finish_reason="length"``) when enabled
                without enough ``max_tokens`` headroom -- callers opting in
                (the DEEP reasoning-level preset) already budget for it.
            max_tokens: Default maximum number of generated tokens.
            request_timeout: Per-request timeout in seconds. Defaults to
                ``settings.EVREN_REQUEST_TIMEOUT_SECONDS`` -- Evren's own
                documented recommendation (up to 1800s on shared hardware).
        """
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model
        self.temperature = temperature
        self.reasoning = reasoning
        self.max_tokens = max_tokens
        self.request_timeout = (
            request_timeout
            if request_timeout is not None
            else settings.EVREN_REQUEST_TIMEOUT_SECONDS
        )
        self._client_cache: dict[tuple, ChatOpenAI] = {}
        logger.info(
            "Initialized EvrenClient base_url=%s model=%s temperature=%s "
            "reasoning=%s max_tokens=%s timeout=%s",
            base_url,
            model,
            temperature,
            reasoning,
            max_tokens,
            self.request_timeout,
        )

    def _build_client(
        self,
        temperature: float,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ChatOpenAI:
        """Return a configured Evren client, reusing one per parameter set.

        Args:
            temperature: Sampling temperature for this call.
            max_tokens: Generation budget, falling back to the client default.
            **kwargs: Extra options. ``reasoning`` is consumed here and
                translated to ``enable_thinking``; anything else is forwarded
                to ``ChatOpenAI``.

        Returns:
            A cached or newly built ``ChatOpenAI``.
        """
        reasoning = kwargs.pop("reasoning", self.reasoning)
        num_predict = max_tokens if max_tokens is not None else self.max_tokens

        try:
            extra_key = tuple(sorted(kwargs.items()))
            cacheable = True
        except TypeError:
            extra_key = ()
            cacheable = False

        cache_key = (temperature, num_predict, reasoning, extra_key)
        if cacheable and cache_key in self._client_cache:
            return self._client_cache[cache_key]

        # enable_thinking must be sent explicitly on every call, never
        # omitted. Verified live against the real API: llm-large defaults to
        # thinking-mode ON for a sufficiently complex prompt even when this
        # key is absent entirely -- reproduced directly with the production
        # writer prompt (9.7k-char system + 5.3k-char user message), which
        # burned the full 2048-token budget on hidden reasoning_content and
        # returned finish_reason="length" with zero actual content. Omitting
        # this key is not the same as disabling reasoning, which is why the
        # earlier version (only sending it when reasoning=True) produced
        # empty drafts by default. Both the top-level and vLLM's
        # chat_template_kwargs-nested spellings are sent since Evren's docs
        # don't pin down which one the deployed engine reads -- verified
        # live that both are honoured.
        extra_body: dict[str, Any] = {
            "enable_thinking": reasoning,
            "chat_template_kwargs": {"enable_thinking": reasoning},
        }

        client = ChatOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model_name,
            temperature=temperature,
            max_tokens=num_predict,
            timeout=self.request_timeout,
            extra_body=extra_body,
            **kwargs,
        )
        if cacheable:
            self._client_cache[cache_key] = client
        return client

    async def generate(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        """Generate response from a list of messages using Evren."""
        temp = temperature if temperature is not None else self.temperature

        client = self._build_client(temp, max_tokens, **kwargs)
        lc_messages = convert_messages(messages)

        started = time.perf_counter()
        try:
            response = await client.ainvoke(lc_messages)
        except Exception:
            logger.exception("Error generating response from Evren")
            raise

        logger.info(
            "Evren generate model=%s took=%.2fs",
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
        """Stream response chunk-by-chunk using Evren."""
        temp = temperature if temperature is not None else self.temperature

        client = self._build_client(temp, max_tokens, **kwargs)
        lc_messages = convert_messages(messages)

        try:
            async for chunk in client.astream(lc_messages):
                text = str(chunk.content)
                if text:
                    yield text
        except Exception:
            logger.exception("Error streaming response from Evren")
            raise

    async def generate_structured(
        self,
        messages: list[dict[str, str]],
        response_model: Any,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """Generate structured output validated against a Pydantic model.

        Thinking mode is forced off, same reason as ``OllamaClient``: reasoning
        tokens precede the JSON body, consume the token budget, and Evren's
        own troubleshooting docs document exactly this failure mode (empty
        content, ``finish_reason="length"``) for structured/short outputs.

        ``method="function_calling"`` is pinned rather than relying on
        ``with_structured_output``'s ``"json_schema"`` default, mirroring
        ``OllamaClient.generate_structured`` -- native tool-calling is the
        structured-output path verified to work reliably against
        vLLM-served Qwen models.
        """
        temp = temperature if temperature is not None else self.temperature
        max_tokens = kwargs.pop("max_tokens", None)
        kwargs.setdefault("reasoning", False)
        client = self._build_client(temp, max_tokens, **kwargs)

        lc_messages = convert_messages(messages)

        started = time.perf_counter()
        try:
            structured_llm = client.with_structured_output(
                response_model, method="function_calling"
            )
            result = await structured_llm.ainvoke(lc_messages)
        except Exception:
            logger.exception("Error generating structured response from Evren")
            raise

        logger.info(
            "Evren structured model=%s schema=%s took=%.2fs",
            self.model_name,
            getattr(response_model, "__name__", response_model),
            time.perf_counter() - started,
        )
        return result

    async def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ToolCallResponse:
        """Generate one turn of a tool-calling exchange via ``bind_tools``.

        Thinking mode is forced off for the same reason ``generate_structured``
        forces it off: reasoning tokens would precede the tool-call payload
        and can consume the generation budget before it.
        """
        temp = temperature if temperature is not None else self.temperature
        kwargs.setdefault("reasoning", False)
        client = self._build_client(temp, max_tokens, **kwargs)
        lc_messages = convert_messages(messages)

        started = time.perf_counter()
        try:
            bound = client.bind_tools(tools)
            response = await bound.ainvoke(lc_messages)
        except Exception:
            logger.exception("Error generating tool-call response from Evren")
            raise

        logger.info(
            "Evren generate_with_tools model=%s tool_calls=%d took=%.2fs",
            self.model_name,
            len(response.tool_calls or []),
            time.perf_counter() - started,
        )
        return ToolCallResponse(
            content=str(response.content or ""),
            tool_calls=[
                {
                    "id": call.get("id") or "",
                    "name": call.get("name", ""),
                    "args": call.get("args") or {},
                }
                for call in (response.tool_calls or [])
            ],
        )

    async def warm_up(self) -> bool:
        """No-op: Evren is a remote, shared-hardware service.

        Unlike a local Ollama instance, there is no model to load into
        process memory, and sending a speculative request on startup would
        just spend a fraction of a rate-limited team quota for no benefit.

        Returns:
            Always True.
        """
        logger.info(
            "Skipping warm-up for Evren model '%s' (remote provider).",
            self.model_name,
        )
        return True
