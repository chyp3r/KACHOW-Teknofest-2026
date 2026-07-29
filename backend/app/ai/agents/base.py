import logging
import time
from abc import ABC
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union

from pydantic import BaseModel

from app.ai.llms.base import BaseLLMClient

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """SOTA (State-of-the-Art) Base Agent class providing a unified, robust framework

    for building Specialized Agents in a Multi-Agent system.

    Key Features:
    1. **Unified Messaging**: Supports single prompts or multi-message histories.
    2. **Dynamic Prompting**: System prompt dynamically renders variables using Jinja2-style
       formatting context (e.g., date, profile, dynamic variables).
    3. **Pre/Post-Execution Guardrails**: Custom validator hooks to check inputs or outputs
       and raise structured exceptions or trigger self-correction.
    4. **Observability**: Built-in latency tracing, attempt tracking, and logging.
    5. **Self-Correction Loop**: Automatic retry with error feedback when structured (JSON/Pydantic)
       generation schema validation fails.
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
            name: Human-readable name of the agent (e.g., "NERAgent").
            description: Quick summary of what this agent does (for routing/orchestration).
            system_prompt: Base system instructions containing optional format placeholders.
            tools: Optional tools list that the agent has access to.
            validators: Optional post-generation validator functions.
        """
        self.llm_client = llm_client
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.validators = validators or []
        logger.info(f"Initialized Agent [{self.name}]: {self.description}")

    def _render_system_prompt(self, context: Optional[Dict[str, Any]] = None) -> str:
        """Render system prompt using context variables."""
        if not context:
            return self.system_prompt
        try:
            return self.system_prompt.format(**context)
        except KeyError as e:
            logger.warning(
                f"Missing key in rendering prompt context for [{self.name}]: {e}"
            )
            return self.system_prompt
        except Exception as e:
            logger.error(
                f"Error rendering system prompt for [{self.name}]: {e}", exc_info=True
            )
            return self.system_prompt

    def _prepare_messages(
        self,
        messages: Union[str, List[Dict[str, str]]],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, str]]:
        """Prepares message list by injecting the rendered system prompt at the beginning."""
        rendered_sys = self._render_system_prompt(context)
        prepared = [{"role": "system", "content": rendered_sys}]

        if isinstance(messages, str):
            prepared.append({"role": "user", "content": messages})
        else:
            # If system prompt is already present in the list, filter it out to avoid duplication
            for msg in messages:
                if msg.get("role") != "system":
                    prepared.append(msg)

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
        """
        start_time = time.time()
        logger.info(f"Agent [{self.name}] starting generation...")

        prepared = self._prepare_messages(messages, context)

        try:
            response = await self.llm_client.generate(
                messages=prepared,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            # Apply output validation/guardrails
            for validator in self.validators:
                validator(response)

            latency = time.time() - start_time
            logger.info(
                f"Agent [{self.name}] generation successful in {latency:.4f}s"
            )
            return response
        except Exception as e:
            logger.error(
                f"Agent [{self.name}] execution failed: {e}", exc_info=True
            )
            raise

    async def run_structured(
        self,
        messages: Union[str, List[Dict[str, str]]],
        response_model: type[BaseModel],
        context: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = None,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> Any:
        """Execute the agent to get a structured response conforming to a Pydantic model.

        Includes a self-correction mechanism to retry with error feedback if schema
        validation fails.

        Args:
            messages: Prompt string or message history list.
            response_model: Pydantic model class to validate the output against.
            context: Variables to inject into the system prompt template.
            temperature: Generation temperature.
            max_retries: Number of attempts to correct formatting errors.
            **kwargs: Extra model/provider configurations.
        """
        start_time = time.time()
        logger.info(
            f"Agent [{self.name}] starting structured generation for model [{response_model.__name__}]..."
        )

        prepared = self._prepare_messages(messages, context)

        for attempt in range(1, max_retries + 1):
            try:
                result = await self.llm_client.generate_structured(
                    messages=prepared,
                    response_model=response_model,
                    temperature=temperature,
                    **kwargs,
                )
                latency = time.time() - start_time
                logger.info(
                    f"Agent [{self.name}] structured generation successful on attempt {attempt}/{max_retries} (Took {latency:.4f}s)"
                )
                return result
            except Exception as e:
                logger.warning(
                    f"Agent [{self.name}] structured output validation failed on attempt {attempt}/{max_retries}: {e}"
                )
                if attempt == max_retries:
                    logger.error(
                        f"Agent [{self.name}] failed structured generation after {max_retries} attempts."
                    )
                    raise

                # Self-correction feedback loop: append warning and retry
                prepared.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your last output was invalid. It failed to conform to the requested "
                            f"Pydantic schema {response_model.__name__}. Error trace: {e}. "
                            f"Please regenerate and ensure the output exactly matches the schema."
                        ),
                    }
                )

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
        """
        prepared = self._prepare_messages(messages, context)
        return self.llm_client.stream(
            messages=prepared,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
