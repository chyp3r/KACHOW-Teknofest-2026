from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Dict, Any, Optional


class BaseLLMClient(ABC):
    """Abstract base class representing a unified interface for all LLM providers."""

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> str:
        """Generate response from a list of messages.

        Args:
            messages: List of message dicts (e.g., [{"role": "user", "content": "hi"}])
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Extra provider-specific parameters
        """
        pass

    @abstractmethod
    def stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> AsyncIterator[str]:
        """Stream the generated response chunk-by-chunk.

        Args:
            messages: List of message dicts
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Extra provider-specific parameters
        """
        pass

    @abstractmethod
    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        response_model: Any,
        temperature: Optional[float] = None,
        **kwargs: Any
    ) -> Any:
        """Generate structured output validated against a Pydantic model.

        Args:
            messages: List of message dicts
            response_model: Pydantic model class to validate the output against
            temperature: Sampling temperature
            **kwargs: Extra provider-specific parameters
        """
        pass

    def _format_prompt(
        self, prompt: str, system_prompt: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """Helper to format a simple prompt and system prompt into a standard message list."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> str:
        """Convenience method to generate text directly from a prompt string."""
        messages = self._format_prompt(prompt, system_prompt)
        return await self.generate(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

    def stream_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> AsyncIterator[str]:
        """Convenience method to stream response directly from a prompt string."""
        messages = self._format_prompt(prompt, system_prompt)
        return self.stream(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
