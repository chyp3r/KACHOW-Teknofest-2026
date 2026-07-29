import logging
from typing import AsyncIterator, List, Dict, Any, Optional

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
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
    ):
        """Initialize the Ollama client.

        Args:
            base_url: The URL where the local Ollama instance is running.
            model: The name of the model to use (e.g. "qwen3.5:9b").
            temperature: Default temperature for generation.
        """
        self.base_url = base_url
        self.model_name = model
        self.temperature = temperature
        logger.info(
            f"Initialized OllamaClient with base_url={base_url}, model={model}, temperature={temperature}"
        )

    def _convert_messages(self, messages: List[Dict[str, str]]) -> List[BaseMessage]:
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
                logger.warning(f"Unknown message role: {role}, defaulting to HumanMessage")
                lc_messages.append(HumanMessage(content=content))
        return lc_messages

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> str:
        """Generate response from a list of messages using local Ollama."""
        temp = temperature if temperature is not None else self.temperature
        
        # Build client parameters
        client_kwargs = {
            "base_url": self.base_url,
            "model": self.model_name,
            "temperature": temp,
            **kwargs
        }
        if max_tokens is not None:
            client_kwargs["num_predict"] = max_tokens

        client = ChatOllama(**client_kwargs)
        lc_messages = self._convert_messages(messages)

        try:
            response = await client.ainvoke(lc_messages)
            return str(response.content)
        except Exception as e:
            logger.error(f"Error generating response from Ollama: {e}", exc_info=True)
            raise

    async def stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> AsyncIterator[str]:
        """Stream response chunk-by-chunk using local Ollama."""
        temp = temperature if temperature is not None else self.temperature
        
        # Build client parameters
        client_kwargs = {
            "base_url": self.base_url,
            "model": self.model_name,
            "temperature": temp,
            **kwargs
        }
        if max_tokens is not None:
            client_kwargs["num_predict"] = max_tokens

        client = ChatOllama(**client_kwargs)
        lc_messages = self._convert_messages(messages)

        try:
            async for chunk in client.astream(lc_messages):
                yield str(chunk.content)
        except Exception as e:
            logger.error(f"Error streaming response from Ollama: {e}", exc_info=True)
            raise

    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        response_model: Any,
        temperature: Optional[float] = None,
        **kwargs: Any
    ) -> Any:
        """Generate structured output validated against a Pydantic model using Ollama."""
        temp = temperature if temperature is not None else self.temperature
        
        client = ChatOllama(
            base_url=self.base_url,
            model=self.model_name,
            temperature=temp,
            **kwargs
        )
        
        lc_messages = self._convert_messages(messages)
        
        try:
            structured_llm = client.with_structured_output(response_model)
            return await structured_llm.ainvoke(lc_messages)
        except Exception as e:
            logger.error(f"Error generating structured response from Ollama: {e}", exc_info=True)
            raise
