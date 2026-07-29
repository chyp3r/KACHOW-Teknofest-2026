import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.ai.llms.base import BaseLLMClient

logger = logging.getLogger(__name__)


class vLLMClient(BaseLLMClient):
    """Client for interacting with a vLLM instance using LangChain's OpenAI wrapper."""

    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.7,
        api_key: str = "EMPTY",
    ):
        """Initialize the vLLM client.

        Args:
            base_url: The URL where the vLLM instance is running (e.g. "http://localhost:8000/v1").
            model: The name of the model to use.
            temperature: Default temperature for generation.
            api_key: Optional API key (defaults to "EMPTY" for local instances).
        """
        self.base_url = base_url
        self.model_name = model
        self.temperature = temperature
        self.api_key = api_key
        logger.info(
            f"Initialized vLLMClient with base_url={base_url}, model={model}, temperature={temperature}"
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
        """Generate response from a list of messages using vLLM."""
        temp = temperature if temperature is not None else self.temperature
        
        # Build client parameters using standard langchain_openai ChatOpenAI wrapper
        client = ChatOpenAI(
            openai_api_base=self.base_url,
            openai_api_key=self.api_key,
            model_name=self.model_name,
            temperature=temp,
            max_tokens=max_tokens,
            **kwargs
        )
        lc_messages = self._convert_messages(messages)

        try:
            response = await client.ainvoke(lc_messages)
            return str(response.content)
        except Exception as e:
            logger.error(f"Error generating response from vLLM: {e}", exc_info=True)
            raise

    async def stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> AsyncIterator[str]:
        """Stream response chunk-by-chunk using vLLM."""
        temp = temperature if temperature is not None else self.temperature
        
        client = ChatOpenAI(
            openai_api_base=self.base_url,
            openai_api_key=self.api_key,
            model_name=self.model_name,
            temperature=temp,
            max_tokens=max_tokens,
            **kwargs
        )
        lc_messages = self._convert_messages(messages)

        try:
            async for chunk in client.astream(lc_messages):
                yield str(chunk.content)
        except Exception as e:
            logger.error(f"Error streaming response from vLLM: {e}", exc_info=True)
            raise

    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        response_model: Any,
        temperature: Optional[float] = None,
        **kwargs: Any
    ) -> Any:
        """Generate structured output validated against a Pydantic model using vLLM."""
        temp = temperature if temperature is not None else self.temperature
        
        client = ChatOpenAI(
            openai_api_base=self.base_url,
            openai_api_key=self.api_key,
            model_name=self.model_name,
            temperature=temp,
            **kwargs
        )
        
        lc_messages = self._convert_messages(messages)
        
        try:
            structured_llm = client.with_structured_output(response_model)
            return await structured_llm.ainvoke(lc_messages)
        except Exception as e:
            logger.error(f"Error generating structured response from vLLM: {e}", exc_info=True)
            raise
