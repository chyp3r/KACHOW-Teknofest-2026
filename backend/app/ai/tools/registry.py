"""Declarative tool specs and their LangChain binding.

Mirrors the ``STEP_SPECS``/``STEP_RUNNERS`` split in
:mod:`app.ai.workflows.step_graph`: a ``ToolSpec`` is data (name, description,
argument schema) plus the one callable that actually does the work, kept apart
from how a specific LLM provider wants tools declared.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

__all__ = ["ToolSpec", "to_langchain_tool"]


@dataclass(frozen=True)
class ToolSpec:
    """One tool the assistant agent may call.

    Attributes:
        name: Stable tool name, as the model will refer to it in a tool call.
        description: What the tool does and when to call it -- this is the
            only thing the model sees to decide whether it needs the tool, so
            it has to describe the *result*, not the implementation.
        args_schema: Pydantic model describing the tool's arguments.
        handler: Async callable that performs the tool's work and returns the
            text to feed back to the model. Invoked directly by the assistant
            agent's own loop -- never by LangChain's tool executor, which only
            ever sees :func:`to_langchain_tool`'s schema-only stand-in.
    """

    name: str
    description: str
    args_schema: type[BaseModel]
    handler: Callable[..., Awaitable[str]]


def to_langchain_tool(spec: ToolSpec) -> StructuredTool:
    """Build the schema-only LangChain tool a provider's ``bind_tools`` needs.

    The returned tool is never executed by LangChain itself -- the assistant
    agent inspects ``AIMessage.tool_calls`` after a bound call and invokes
    ``spec.handler`` directly, matching by name. This stand-in only exists
    because ``bind_tools`` needs *something* bindable to derive the tool
    schema (name, description, JSON schema for arguments) that gets sent to
    the model.

    Args:
        spec: The tool to bind.

    Returns:
        A ``StructuredTool`` carrying ``spec``'s schema.
    """

    async def _unused(**_kwargs: Any) -> str:
        raise RuntimeError(
            f"'{spec.name}' must be invoked via ToolSpec.handler, not "
            "LangChain's own tool executor."
        )

    return StructuredTool.from_function(
        name=spec.name,
        description=spec.description,
        args_schema=spec.args_schema,
        coroutine=_unused,
    )
