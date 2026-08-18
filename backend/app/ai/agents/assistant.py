import logging
from typing import Any, AsyncIterator, Optional

from langchain_core.runnables import RunnableConfig

from app.ai.agents.base import BaseAgent
from app.ai.identity.company_profile import CompanyProfile
from app.ai.identity.injection import format_agent_identity
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager, get_prompt_manager
from app.ai.tools.registry import ToolSpec, to_langchain_tool
from app.observability.ai_metrics import LLM_TOKENS

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
        security_boundary: Optional[str] = None,
        agent_identity: Optional[str] = None,
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
            security_boundary: A short Turkish note describing the
                requester's clearance and the attached document's
                confidentiality level (see
                ``app.ai.workflows.planning_graph._build_security_boundary_note``).
                A secondary, prompt-level layer only -- the deterministic
                checks (``document_tools.py``'s deny-at-retrieval,
                ``output_gate.py``) are what actually enforce the boundary;
                this exists to catch the paraphrase case a regex can't see.
            agent_identity: Rendered ``{{agent_identity}}`` text -- the
                requesting company's own identity (see
                ``app.ai.identity.injection.format_agent_identity``), or the
                system default when no company profile is configured.
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
            "security_boundary": security_boundary
            or "Bu oturum için bilinen bir yetki kısıtlaması yok.",
            "agent_identity": agent_identity or format_agent_identity(CompanyProfile.empty("")),
        }
        messages = self._prepare_messages(
            [*history, {"role": "user", "content": query}], context=context
        )

        tools_by_name = {tool.name: tool for tool in tools}
        lc_tools = [to_langchain_tool(tool) for tool in tools]

        # Set only when a generate_with_tools turn ends the loop cleanly (no
        # further tool calls) with a non-empty answer already in hand -- the
        # common shape for a converged tool turn. Left None on every other
        # exit (a turn's own call raised, MAX_TOOL_TURNS ran out with a tool
        # call still pending, or no tools were bound at all) so those keep
        # falling through to the real stream() call below exactly as before.
        final_response_content: Optional[str] = None
        for _ in range(MAX_TOOL_TURNS if lc_tools else 0):
            try:
                response = await self.llm_client.generate_with_tools(
                    messages=messages, tools=lc_tools, temperature=0.2
                )
            except Exception:
                logger.exception("AssistantAgent tool-call turn failed")
                break

            if not response.tool_calls:
                final_response_content = response.content
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

        # Reuse the tool loop's own answer when it already converged instead
        # of paying for a second full generation pass to say the same thing:
        # on a real request this was the difference between two Ollama calls
        # and three, and the third was what pushed the "assist" node past its
        # node_budget ceiling (app/ai/policy/schema.py) often enough to matter.
        # Falls through to the original unconditional stream() whenever there
        # is no such answer yet (see final_response_content's own comment).
        final_chunks: list[str] = []
        if final_response_content:
            final_chunks.append(final_response_content)
            yield final_response_content
        else:
            async for chunk in self.llm_client.stream(messages=messages, temperature=0.2):
                final_chunks.append(chunk)
                yield chunk

        # Measured against `messages` as it stands right before the final
        # call -- the largest the prompt gets this turn (tool turns already
        # folded in), which is exactly the context-overflow risk moment.
        prompt_text = "\n".join(msg.get("content", "") or "" for msg in messages)
        LLM_TOKENS.labels(agent=self.name, kind="prompt").inc(
            self.llm_client.count_tokens(prompt_text)
        )
        LLM_TOKENS.labels(agent=self.name, kind="completion").inc(
            self.llm_client.count_tokens("".join(final_chunks))
        )
