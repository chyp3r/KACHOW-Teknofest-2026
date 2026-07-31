import logging
import time
from abc import ABC
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union

from pydantic import BaseModel

from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import render_placeholders

logger = logging.getLogger(__name__)

#: Two attempts, not three. Every retry re-runs a full local generation; on
#: consumer hardware a third attempt costs more wall-clock time than the caller's
#: whole latency budget and almost never succeeds where the second failed.
DEFAULT_MAX_RETRIES = 2


class BaseAgent(ABC):
    """Base class for the specialized agents in the multi-agent system.

    Responsibilities:

    1. **Unified messaging** -- accepts a single prompt or a message history.
    2. **Prompt rendering** -- substitutes ``{{variable}}`` placeholders. This is
       deliberately *not* :meth:`str.format`: the prompt templates contain
       literal JSON examples with single braces, so ``format`` raises ``KeyError``
       on them and the previous implementation swallowed that error and silently
       shipped an unrendered prompt.
    3. **Guardrails** -- optional post-generation validators.
    4. **Observability** -- per-call latency logging.
    5. **Self-correction** -- bounded retry with error feedback when structured
       output fails schema validation.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        name: str,
        description: str,
        system_prompt: str,
        tools: Optional[List[Any]] = None,
        validators: Optional[List[Callable[[str], None]]] = None,
    ):
        """Initialize the Base Agent.

        Args:
            llm_client: The LLM provider client conforming to BaseLLMClient.
            name: Human-readable name of the agent (e.g., "ClassifierAgent").
            description: Quick summary of what this agent does.
            system_prompt: Base instructions, optionally with ``{{placeholders}}``.
            tools: Optional tools list that the agent has access to.
            validators: Optional post-generation validator functions.
        """
        self.llm_client = llm_client
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.validators = validators or []
        logger.info("Initialized Agent [%s]: %s", self.name, self.description)

    def _render_system_prompt(self, context: Optional[Dict[str, Any]] = None) -> str:
        """Substitute ``{{variable}}`` placeholders in the system prompt.

        Args:
            context: Values to inject. ``None`` returns the template untouched.

        Returns:
            The rendered prompt. Unknown placeholders are left in place rather
            than raising, so a partially supplied context still produces a usable
            prompt instead of a silently blank one.
        """
        if not context:
            return self.system_prompt
        return render_placeholders(self.system_prompt, context)

    def _prepare_messages(
        self,
        messages: Union[str, List[Dict[str, str]]],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, str]]:
        """Build the message list, prefixing the rendered system prompt.

        Args:
            messages: Prompt string or message history list.
            context: Variables to inject into the system prompt template.

        Returns:
            A message list beginning with exactly one system message.
        """
        prepared = [{"role": "system", "content": self._render_system_prompt(context)}]

        if isinstance(messages, str):
            prepared.append({"role": "user", "content": messages})
        else:
            # Drop any caller-supplied system turns; the agent owns that slot.
            prepared.extend(
                msg for msg in messages if msg.get("role") != "system"
            )

        return prepared

    async def run(
        self,
        messages: Union[str, List[Dict[str, str]]],
        context: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """Execute the agent run and return the text response.

        Args:
            messages: Prompt string or message history list.
            context: Variables to inject into the system prompt template.
            temperature: Generation temperature.
            max_tokens: Limit on maximum tokens.
            **kwargs: Extra model/provider configurations.

        Returns:
            The generated text.

        Raises:
            Exception: Whatever the provider or a validator raised.
        """
        start_time = time.perf_counter()
        prepared = self._prepare_messages(messages, context)

        try:
            response = await self.llm_client.generate(
                messages=prepared,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            for validator in self.validators:
                validator(response)

            logger.info(
                "Agent [%s] generated %d chars in %.2fs",
                self.name,
                len(response),
                time.perf_counter() - start_time,
            )
            return response
        except Exception:
            logger.exception("Agent [%s] execution failed", self.name)
            raise

    async def run_structured(
        self,
        messages: Union[str, List[Dict[str, str]]],
        response_model: type[BaseModel],
        context: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        **kwargs: Any,
    ) -> Any:
        """Execute the agent and validate the output against a Pydantic model.

        On failure the agent retries with a correction note appended. The note
        replaces the previous one instead of stacking: the original
        implementation appended to the same list every round, so by the third
        attempt the (potentially multi-thousand-token) source document was being
        re-sent three times over.

        Args:
            messages: Prompt string or message history list.
            response_model: Pydantic model class to validate the output against.
            context: Variables to inject into the system prompt template.
            temperature: Generation temperature.
            max_retries: Total number of attempts, including the first.
            **kwargs: Extra model/provider configurations.

        Returns:
            A validated ``response_model`` instance.

        Raises:
            Exception: The last provider or validation error, if every attempt
                failed.
        """
        start_time = time.perf_counter()
        base_messages = self._prepare_messages(messages, context)
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            attempt_messages = list(base_messages)
            if last_error is not None:
                attempt_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Önceki yanıtın geçersizdi ve "
                            f"{response_model.__name__} şemasına uymadı. "
                            f"Hata: {last_error}. "
                            "Yalnızca şemaya birebir uyan geçerli bir JSON nesnesi "
                            "üret; açıklama, markdown veya ek metin ekleme."
                        ),
                    }
                )

            try:
                result = await self.llm_client.generate_structured(
                    messages=attempt_messages,
                    response_model=response_model,
                    temperature=temperature,
                    **kwargs,
                )
                logger.info(
                    "Agent [%s] structured %s ok on attempt %d/%d in %.2fs",
                    self.name,
                    response_model.__name__,
                    attempt,
                    max_retries,
                    time.perf_counter() - start_time,
                )
                return result
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Agent [%s] structured output invalid on attempt %d/%d: %s",
                    self.name,
                    attempt,
                    max_retries,
                    exc,
                )

        logger.error(
            "Agent [%s] failed structured generation of %s after %d attempts.",
            self.name,
            response_model.__name__,
            max_retries,
        )
        raise last_error  # type: ignore[misc]

    def stream(
        self,
        messages: Union[str, List[Dict[str, str]]],
        context: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream the agent response chunk-by-chunk.

        Args:
            messages: Prompt string or message history list.
            context: Variables to inject into the system prompt template.
            temperature: Generation temperature.
            max_tokens: Limit on maximum tokens.
            **kwargs: Extra model/provider configurations.

        Returns:
            An async iterator of text chunks.
        """
        prepared = self._prepare_messages(messages, context)
        return self.llm_client.stream(
            messages=prepared,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
