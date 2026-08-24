import logging

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

logger = logging.getLogger(__name__)


def convert_messages(messages: list[dict]) -> list[BaseMessage]:
    """Convert standard message dicts to LangChain Message objects.

    Shared by every ``BaseLLMClient`` implementation that talks to a
    LangChain chat model (``OllamaClient``, ``EvrenClient``): the mapping is
    provider-agnostic, just a dict -> ``BaseMessage`` translation.

    Two roles beyond the original three exist to round-trip a tool-calling
    loop: an ``assistant`` message may carry a ``tool_calls`` key (the
    model's own previous turn requesting one or more tools), and a ``tool``
    message carries that turn's result (``tool_call_id``, ``name``,
    ``content``). Both are plain JSON-safe dicts rather than raw LangChain
    objects so the caller's message list stays serializable (useful for SSE
    debug logging) between loop turns.
    """
    lc_messages: list[BaseMessage] = []
    for msg in messages:
        role = msg.get("role", "user").lower()
        content = msg.get("content", "")
        if role == "system":
            lc_messages.append(SystemMessage(content=content))
        elif role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role in ("assistant", "ai"):
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                lc_messages.append(AIMessage(content=content, tool_calls=tool_calls))
            else:
                lc_messages.append(AIMessage(content=content))
        elif role == "tool":
            lc_messages.append(
                ToolMessage(
                    content=content,
                    tool_call_id=msg.get("tool_call_id", ""),
                    name=msg.get("name"),
                )
            )
        else:
            logger.warning(
                "Unknown message role: %s, defaulting to HumanMessage", role
            )
            lc_messages.append(HumanMessage(content=content))

    # A chat model given only a system turn has nothing to respond to and
    # some providers emit an empty completion. Guarantee a user turn.
    if lc_messages and all(isinstance(m, SystemMessage) for m in lc_messages):
        lc_messages.append(HumanMessage(content="Yönergeye göre yanıt üret."))
    return lc_messages
