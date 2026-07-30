import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from app.ai.llms.base import BaseLLMClient

logger = logging.getLogger(__name__)


class OllamaClient(BaseLLMClient):
    """Client for interacting with a local Ollama instance using LangChain."""

    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.7,
        reasoning: bool = False,
        max_tokens: int = 1024,
    ):
        """Initialize the Ollama client.

        Args:
            base_url: The URL where the local Ollama instance is running.
            model: The name of the model to use.
            temperature: Default temperature for generation.
            reasoning: Whether the model should use its thinking mode.
            max_tokens: Default maximum number of generated tokens.
        """
        self.base_url = base_url
        self.model_name = model
        self.temperature = temperature
        self.reasoning = reasoning
        self.max_tokens = max_tokens
        logger.info(
            "Initialized OllamaClient with base_url=%s, model=%s, "
            "temperature=%s, reasoning=%s, max_tokens=%s",
            base_url,
            model,
            temperature,
            reasoning,
            max_tokens,
        )

    def _build_client(
        self,
        temperature: float,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ChatOllama:
        """Build a consistently configured Ollama client."""
        reasoning = kwargs.pop("reasoning", self.reasoning)
        num_predict = kwargs.pop(
            "num_predict",
            max_tokens if max_tokens is not None else self.max_tokens,
        )
        return ChatOllama(
            base_url=self.base_url,
            model=self.model_name,
            temperature=temperature,
            reasoning=reasoning,
            num_predict=num_predict,
            **kwargs,
        )

    def _convert_messages(self, messages: list[dict[str, str]]) -> list[BaseMessage]:
        """Convert standard message dicts to LangChain Message objects."""
        lc_messages = []
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
                    f"Unknown message role: {role}, defaulting to HumanMessage"
                )
                lc_messages.append(HumanMessage(content=content))
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

        try:
            response = await client.ainvoke(lc_messages)
            return str(response.content)
        except Exception:
            logger.exception("Error generating response from Ollama")
            raise

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
                yield str(chunk.content)
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
        """Generate structured output validated against a Pydantic model using Ollama."""
        temp = temperature if temperature is not None else self.temperature
        max_tokens = kwargs.pop("max_tokens", None)
        client = self._build_client(temp, max_tokens, **kwargs)

        lc_messages = self._convert_messages(messages)

        try:
            structured_llm = client.with_structured_output(response_model)
            return await structured_llm.ainvoke(lc_messages)
        except Exception:
            logger.exception("Error generating structured response from Ollama")
            raise
