import logging
from typing import Any, AsyncIterator, Optional

from langchain_core.runnables import RunnableConfig

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager, get_prompt_manager
from app.ai.tools.registry import ToolSpec, to_langchain_tool

logger = logging.getLogger(__name__)

#: Two tool turns, not more. Each turn is a full local generation; a request
#: that still hasn't converged to an answer after two rounds is more likely a
#: model that keeps re-querying than one that needs a third data point, and a
#: third attempt would blow the "assist" node's time budget for a case that
#: rarely benefits from it.
MAX_TOOL_TURNS = 2


class AssistantAgent(BaseAgent):
    """Answers conversationally, reaching for retrieval tools when it needs to.

    Replaces the previous split between ``ChatAgent`` (conversation only) and
    ``DocumentQAAgent`` (retrieval-grounded, document only): the router used to
    have to decide in advance which of the two a message needed, which is
    exactly the decision a chunk of ``intent_rules.py``/``intent_scorer.py``
    existed to arbitrate. Here the same agent handles both, and the model
    itself decides per-turn whether answering needs a tool call -- see
    ``run_stream``.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        """Initialize the assistant agent.

        Args:
            llm_client: The LLM provider client. Must support
                ``generate_with_tools`` when any tools are bound.
            prompt_manager: Optional prompt manager override.
        """
        manager = prompt_manager or get_prompt_manager()
        super().__init__(
            llm_client=llm_client,
            name="AssistantAgent",
            description="Answers conversationally, calling tools for document/legislation lookups.",
            system_prompt=manager.get_template("assistant"),
        )

    async def run_stream(
        self,
        *,
        query: str,
        history: list[dict[str, str]],
        history_summary: Optional[str] = None,
        document_context: Optional[str] = None,
        tools: list[ToolSpec],
        config: Optional[RunnableConfig] = None,
        node: str = "assist",
    ) -> AsyncIterator[str]:
        """Run the tool loop, then stream the final answer token by token.

        Args:
            query: The user's current message.
            history: Prior conversation turns (already windowed by the caller).
            history_summary: Rolling summary of turns older than the window.
            document_context: Short description of the attached document (title/
                summary), rendered into the system prompt so the model knows
                one is attached even before it calls a tool. The tools
                themselves supply the depth; this is only enough to decide
                whether to reach for them.
            tools: Tools bindable for this turn. Empty when nothing is
                attached (no document, no legislation retriever) -- the loop
                is then skipped entirely and this behaves like a plain chat.
            config: Runnable config, forwarded to tool handlers that invoke a
                sub-graph and used to emit ``tool_call`` progress events.
            node: SSE node id these events are published under.

        Yields:
            Text chunks of the final answer.
        """
        # Deferred: app.ai.workflows.events lives under the app.ai.workflows
        # package, whose __init__ eagerly imports planning_graph, which
        # imports AssistantAgent -- a module-level import here would cycle
        # back into this module before its own class body finished executing.
        # Same reason planner.py imports BaseAgent inside a function instead
        # of at module scope.
        from app.ai.workflows.events import emit_tool_call

        context = {
            "history_summary": history_summary
            or "(Bu konuşmada henüz özetlenecek eski mesaj yok.)",
            "document_context": document_context
            or "(Bu turda yüklenmiş bir belge yok.)",
        }
        messages = self._prepare_messages(
            [*history, {"role": "user", "content": query}], context=context
        )

        tools_by_name = {tool.name: tool for tool in tools}
        lc_tools = [to_langchain_tool(tool) for tool in tools]

        for _ in range(MAX_TOOL_TURNS if lc_tools else 0):
            try:
                response = await self.llm_client.generate_with_tools(
                    messages=messages, tools=lc_tools, temperature=0.2
                )
            except Exception:
                logger.exception("AssistantAgent tool-call turn failed")
                break

            if not response.tool_calls:
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": response.tool_calls,
                }
            )
            for call in response.tool_calls:
                spec = tools_by_name.get(call["name"])
                await emit_tool_call(config, node, call["name"], call.get("args") or {})
                if spec is None:
                    result = f"Bilinmeyen araç: {call['name']}"
                else:
                    try:
                        result = await spec.handler(**(call.get("args") or {}))
                    except Exception as exc:
                        logger.exception("Assistant tool '%s' failed", call["name"])
                        result = f"Araç çalıştırılırken hata oluştu: {exc}"
                messages.append(
                    {
                        "role": "tool",
                        "content": str(result),
                        "tool_call_id": call.get("id", ""),
                        "name": call["name"],
                    }
                )

        # Final answer streamed with no tools bound: guarantees this call
        # produces text rather than yet another tool request, regardless of
        # how many rounds the loop above ran.
        async for chunk in self.llm_client.stream(messages=messages, temperature=0.2):
            yield chunk
