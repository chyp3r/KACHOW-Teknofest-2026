from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, List, Dict, Any, Optional


@dataclass
class ToolCallResponse:
    """One non-streaming turn of a tool-calling exchange.

    Attributes:
        content: Text the model produced alongside (or instead of) tool calls.
            Some providers emit a short remark even when they also request a
            tool; most emit only tool calls with empty content.
        tool_calls: Requested calls, each ``{"id", "name", "args"}``. Empty
            means the model chose to answer directly instead of calling a tool.
    """

    content: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)


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

    @abstractmethod
    async def generate_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Any],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> ToolCallResponse:
        """Generate one turn of a tool-calling exchange.

        Non-streaming: a tool call has to be inspected and executed before
        anything downstream can be shown to the user, so there is nothing
        useful to stream on a turn that might just be a tool request.

        Args:
            messages: Message dicts. Beyond the usual ``system``/``user``/
                ``assistant`` roles, a caller resuming a tool loop may include
                an ``assistant`` message carrying a ``tool_calls`` key (the
                model's own previous turn) and ``tool`` messages carrying
                ``tool_call_id``/``name``/``content`` (that turn's results).
            tools: Tool schemas in this provider's native bindable form (e.g.
                LangChain ``BaseTool`` instances for a LangChain-backed client).
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            **kwargs: Extra provider-specific parameters.

        Returns:
            The model's text (if any) and any tool calls it requested.
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
