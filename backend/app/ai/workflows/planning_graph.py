import asyncio
import hashlib
import json
import logging
import os
import time
from typing import Annotated, Any, Awaitable, Callable, Optional, TypedDict
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.ai.agents.assistant import AssistantAgent
from app.ai.agents.memory_summarizer import MemorySummarizerAgent
from app.ai.context import ContextBlock, ContextBuilder, TokenBudget, select_history_window
from app.ai.context.compress import truncate_with_marker
from app.ai.embeddings.models import BaseEmbeddingsClient
from app.ai.session.focus import SessionFocus, compute_focus_update, merge_focus
from app.ai.llms.base import BaseLLMClient
from app.ai.policy import get_policy
from app.ai.policy.budget import node_budget
from app.ai.response.builder import build_response
from app.ai.retrieval.sparse_encoder import SparseBM25Encoder
from app.ai.semantic.prototype_matcher import PrototypeMatcher
from app.ai.tools.document_tools import build_assistant_tools
from app.ai.verification import apply_answers, verify_draft
from app.ai.workflows.events import (
    child_config,
    emit,
    emit_interrupt,
    emit_node_end,
    emit_node_error,
    emit_node_skipped,
    emit_node_start,
    emit_partial,
    emit_token,
)
from app.ai.workflows.planner import resolve_plan
from app.ai.workflows.revise import run_revise
from app.ai.workflows.step_graph import STEP_SPECS, StepSpec, all_steps_settled, ready_steps
from app.core.config import settings
from app.core.enums.reasoning_level import ReasoningLevel
from app.core.enums.step_status import StepStatus
from app.infrastructure.vectorstore.base import BaseVectorStore
from app.observability.ai_metrics import HITL_INTERRUPTS, NODE_DURATION
from app.observability.run_recorder import end_run, record_step, start_run

logger = logging.getLogger(__name__)

QA_RESULT_LIMIT = get_policy().memory.qa_result_limit

STEP_LABELS = {
    "classification": "Evrak Analizi",
    "draft": "Taslak Oluşturma",
    "routing": "Birim Yönlendirme",
    "assist": "Asistan",
    "revise": "Taslak Revizyonu",
    "clarify": "Açıklayıcı Soru",
}

STEP_MESSAGES = {
    "classification": "Belge sınıflandırılıyor ve üst veriler çıkarılıyor...",
    "draft": "Resmî cevap taslağı hazırlanıyor...",
    "routing": "Cevap taslağının iletileceği birim analiz ediliyor...",
    "assist": "Asistan yanıtı hazırlanıyor...",
    "revise": "Taslak talebe göre güncelleniyor...",
    "clarify": "İsteğinizi netleştirmek için bir soru hazırlanıyor...",
}

def _dependency_failed(
    step: str, state: "PlanningState", updates: dict[str, Any]
) -> Optional[str]:
    """Return the name of a failed dependency for ``step``, if any.

    A step whose dependency's own result carries status FAILED must not run
    on empty/garbage input. Without this a failed draft still let routing
    run on draft="" and route to human approval -- an outcome visually
    identical to a real routing decision. The dependency edges themselves
    live in ``step_graph.STEP_SPECS`` (shared with ``ready_steps``); this
    function is the other half -- *whether a failure* should skip the step,
    which is deliberately not `ready_steps`'s concern (see its docstring).

    Args:
        step: The plan step about to run.
        state: The graph state as of the start of this superstep.
        updates: Updates already computed earlier in this same superstep
            (a dependency that just ran this turn is not yet in ``state``).

    Returns:
        The failed dependency's step name, or None when every dependency (if
        any) succeeded or has not run yet.
    """
    spec = STEP_SPECS.get(step, StepSpec(name=step))
    for dependency in spec.depends_on:
        result = updates.get(f"{dependency}_result") or state.get(f"{dependency}_result") or {}
        if result.get("status") == StepStatus.FAILED:
            return dependency
    return None


#: Turns kept verbatim in the prompt sent to the assist step on every turn.
#: ~6 exchanges is enough for pronoun/ellipsis resolution ("evet, hazırla"
#: after "taslak ister misiniz?") without growing that prompt without bound.
HISTORY_WINDOW = get_policy().memory.history_window

#: Raw turns retained in state before consolidation must have folded them
#: into history_summary. Comfortably larger than HISTORY_WINDOW so
#: consolidate_memory_node always has the overflow available when it runs
#: (it runs once per turn, after HISTORY_WINDOW turns are already appended).
HISTORY_RAW_CAP = get_policy().memory.history_raw_cap

#: Tokens set aside for the assist step's own answer when budgeting its
#: prompt against settings.OLLAMA_NUM_CTX -- a typical conversational reply
#: is well under this; generous on purpose since underestimating here would
#: starve the prompt side for no benefit (the model just stops generating
#: early, the context window doesn't get any bigger).
ASSIST_COMPLETION_RESERVE_TOKENS = 1024

#: Only bother calling the model once there's a worth-while batch to fold in,
#: not for every single turn's 1-2-entry dribble past the window.
CONSOLIDATION_BATCH_SIZE = get_policy().memory.consolidation_batch_size


def _append_history(
    left: list[dict[str, str]] | None, right: list[dict[str, str]] | None
) -> list[dict[str, str]]:
    """LangGraph reducer: concatenate turns and keep only the trailing window.

    Args:
        left: The channel's existing value.
        right: The update returned by a node this superstep.

    Returns:
        The combined, trimmed history.
    """
    combined = [*(left or []), *(right or [])]
    return combined[-HISTORY_RAW_CAP:]


def _pending_consolidation(
    history: list[dict[str, str]],
    summarized_through: int,
    window: int,
    batch_size: int,
) -> tuple[list[dict[str, str]], int]:
    """Turns that have aged out of the verbatim window and aren't summarized yet.

    Args:
        history: The raw retained turns (up to HISTORY_RAW_CAP).
        summarized_through: Count of ``history`` entries already folded into
            ``history_summary``.
        window: The verbatim window size (HISTORY_WINDOW).
        batch_size: Minimum number of newly-overflowed turns worth a model call.

    Returns:
        A tuple of (pending turns, new boundary to advance
        ``summarized_through`` to). ``pending`` is empty when there's nothing
        new past ``window``, or fewer than ``batch_size`` new overflowed turns
        to bother the model for.
    """
    boundary = max(0, len(history) - window)
    pending = history[summarized_through:boundary]
    if len(pending) < batch_size:
        return [], summarized_through
    return pending, boundary


class PlanningState(TypedDict, total=False):
    """LangGraph state for the master orchestration workflow."""

    input_text: str
    document_id: str | None
    #: The authenticated caller, when REQUIRE_AUTH is on (see
    #: ChatService._invoke). None in the open demo/dev path. Read only by
    #: the run-recording hooks in this module -- not otherwise part of any
    #: routing or context-building decision.
    user_id: str | None
    #: This turn's audit-trail id (see app.observability.run_recorder).
    #: Generated fresh in planning_node each turn, like plan_steps -- but
    #: survives a human-in-the-loop pause/resume via the checkpointer
    #: (resuming re-enters the graph at human_gate, not planning_node, so
    #: the *same* run_id is what lets end_run() close out the run it
    #: actually started with).
    run_id: str
    #: Speed-vs-quality tier for this run ("fast"/"balanced"/"deep"); read by
    #: draft_graph via _run_draft. Absent resolves to "balanced" downstream.
    reasoning_level: str
    plan_steps: list[str]
    plan_intent: str
    #: Monotonic turn counter, no longer used to index into `plan_steps`
    #: (see `ready_steps`/`all_steps_settled` in `step_graph.py`) -- kept
    #: only as an ingredient of `human_gate_node`'s interrupt-id hash and
    #: for the step-progress log line.
    current_step_idx: int
    #: Name of the step `execute_step_node` most recently ran, so
    #: `route_after_step` can check "did draft just run" without indexing
    #: `plan_steps[current_step_idx - 1]`.
    _last_ran_step: Optional[str]
    cached_document: dict[str, Any]
    classification_result: dict[str, Any]
    draft_result: dict[str, Any]
    routing_result: dict[str, Any]
    assist_result: dict[str, Any]
    #: revise/clarify write their real payload into draft_result/assist_result
    #: respectively (see _result_key) so downstream code -- human_gate,
    #: routing, focus_node's versioning, the "reply" the user sees -- treats
    #: them uniformly with draft/assist. These two exist only so the
    #: scheduler (step_graph.ready_steps/all_steps_settled, which keys
    #: readiness on `state[f"{step}_result"]` for every step generically)
    #: has something to see -- an update key LangGraph's TypedDict schema
    #: doesn't declare is silently dropped, not stored, which without this
    #: field left both steps looking permanently unsettled and looping.
    revise_result: dict[str, Any]
    clarify_result: dict[str, Any]
    final_output: dict[str, Any]
    #: Persists across separate ainvoke() calls on the same checkpointer
    #: thread_id (see ChatService._thread_id) -- this is the whole memory
    #: story; there is no separate store to keep consistent with it. Holds up
    #: to HISTORY_RAW_CAP raw turns; only the trailing HISTORY_WINDOW are sent
    #: verbatim to the assist step (see _prior_turns).
    history: Annotated[list[dict[str, str]], _append_history]
    #: Rolling summary of turns that have aged out of the verbatim window
    #: (see consolidate_memory_node). Plain string field -- LangGraph's
    #: default "last write wins" channel semantics are exactly what's wanted
    #: here since only consolidate_memory_node ever writes it.
    history_summary: str
    #: Count of `history` entries already folded into history_summary, so
    #: consolidation only summarizes the newly-overflowed delta each turn
    #: instead of re-summarizing the whole backlog.
    history_summarized_through: int
    #: Task-level state (active draft + its version history, the session's
    #: accumulated objective, and -- once later phases exist to populate
    #: them -- a pending clarification and the last-referenced document
    #: anchor). The one PlanningState channel `planning_node` does NOT
    #: reset every turn: everything else here answers "what happened this
    #: turn", this answers "what are we working on across turns". Updated
    #: by `focus_node`, never by `planning_node`. See `app.ai.session.focus`.
    focus: Annotated[SessionFocus, merge_focus]


def _requested_correspondence_type(classification: dict[str, Any]) -> str | None:
    """Read an explicitly classified output correspondence type.

    Args:
        classification: Combined analysis result.

    Returns:
        The requested correspondence type, when the metadata carries one.
    """
    metadata = classification.get("metadata", {}) or {}
    return classification.get("correspondence_type") or metadata.get(
        "correspondence_type"
    )


def _load_cached_document(document_id: str | None) -> dict[str, Any]:
    """Read the cached analysis and extracted text for an uploaded document.

    Args:
        document_id: The document's storage path, or None.

    Returns:
        The cache payload, or an empty dict when there is nothing to load.
    """
    if not document_id:
        return {}

    cache_file = os.path.join(
        settings.LOCAL_STORAGE_DIR, f"{document_id}_analysis.json"
    )
    if not os.path.exists(cache_file):
        return {}

    try:
        with open(cache_file, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        logger.exception("Failed to read cached analysis for %s", document_id)
        return {}


def _mevzuat_context(classification: dict[str, Any]) -> str:
    """Render the legislation the analysis step already retrieved.

    The draft flow no longer runs a separate RAG step. The analysis sub-graph
    retrieves legislation for the document as part of its own work, so a second
    retrieval pass repeated the same query behind an extra LLM call and
    discarded the first result.

    Args:
        classification: The analysis result.

    Returns:
        The excerpts as prompt context, or an empty string.
    """
    parts: list[str] = []

    for index, document in enumerate(classification.get("mevzuat_documents") or [], 1):
        content = getattr(document, "page_content", None)
        if content:
            source = getattr(document, "metadata", {}).get("mevzuat", "bilinmiyor")
            parts.append(f"[DOKÜMAN {index}] (Kaynak: {source})\n{content}")

    for item in classification.get("mevzuat_suggestions") or []:
        if isinstance(item, dict) and item.get("mevzuat"):
            parts.append(f"[MEVZUAT] {item['mevzuat']}: {item.get('aciklama', '')}")

    return "\n\n".join(parts)


def _prior_turns(state: PlanningState, limit: int) -> list[dict[str, str]]:
    """History entries from before the current turn, most-recent last.

    ``planning_node`` always appends the current user turn to ``history``
    before the ``assist`` step runs, so the last entry is always the message
    being answered right now -- excluded here, or it would appear twice once
    the agent appends it again as the live query turn.

    Args:
        state: Current graph state.
        limit: Maximum number of prior turns to return.

    Returns:
        Up to ``limit`` prior turns, oldest first.
    """
    history = state.get("history") or []
    prior = history[:-1] if history else []
    return prior[-limit:] if limit > 0 else []


def create_planning_graph(
    llm_client: BaseLLMClient,
    document_analysis_graph: Any,
    rag_graph: Any,
    draft_graph: Any,
    routing_graph: Any,
    vector_store: BaseVectorStore | None = None,
    embeddings_client: BaseEmbeddingsClient | None = None,
    fast_llm_client: Optional[BaseLLMClient] = None,
    checkpointer: Any = None,
):
    """Create and compile the master orchestration workflow.

    Planning is deterministic (see :mod:`app.ai.workflows.planner`). The previous
    implementation asked a model to choose from a fixed four-way decision table,
    which cost a structured generation plus a retry loop on every single request
    and needed sixty lines of output-shape repair to be usable at all.

    Args:
        llm_client: Quality-tier model, used for the assist step.
        document_analysis_graph: Compiled analysis sub-graph.
        rag_graph: Compiled retrieval sub-graph, also handed to the assist
            step's ``search_legislation`` tool.
        draft_graph: Compiled drafting sub-graph.
        routing_graph: Compiled routing sub-graph.
        vector_store: Vector store backing the assist step's document search.
        embeddings_client: Embeddings client backing the assist step's
            document search.
        fast_llm_client: Small model for intent classification on ambiguous
            messages. Falls back to ``llm_client``.
        checkpointer: Optional LangGraph checkpointer (see
            ``app.infrastructure.checkpointing``). Required for the
            ``human_gate`` node's ``interrupt()`` calls to actually pause and
            resume the run; without one, HITL steps are skipped and the graph
            falls through as if they never triggered -- degraded, not broken.
            Only this graph gets a checkpointer: the four sub-graphs are
            invoked via ``.ainvoke()`` from inside ``execute_step_node``
            rather than registered as nodes, so they are independent Pregel
            instances that would each need their own unrelated checkpoint
            lineage.

    Returns:
        The compiled LangGraph workflow.
    """
    has_checkpointer = checkpointer is not None
    assistant_agent = AssistantAgent(llm_client)
    # Sized against llm_client.count_tokens -- the same client the assist
    # step's real generation call goes through, so the budget enforced here
    # matches what the provider actually sees.
    context_builder = ContextBuilder(llm_client)
    intent_client = fast_llm_client or llm_client
    # Reuses the fast tier already resolved for intent classification -- a
    # short consolidation pass doesn't warrant a third model in the mix.
    memory_summarizer_agent = MemorySummarizerAgent(intent_client)
    # Unfit on purpose, same as the indexing side (documents/service.py):
    # its sparse indices are corpus-independent CRC32 hashes, and query-side
    # IDF weights default to a uniform 1.0 without a fitted vocabulary, which
    # is still a meaningful lexical signal for RRF fusion against the dense
    # vector.
    qa_sparse_encoder = SparseBM25Encoder()

    # Layer 2 of the intent ladder. Built once per graph, and only when there is
    # an embeddings client to build it with -- without one the ladder simply
    # skips the rung, exactly as it behaved before the layer existed. The
    # matcher disables itself on a stale or missing vector file too, so a
    # deployment that never ran scripts/build_prototypes.py degrades rather
    # than fails.
    prototype_matcher: PrototypeMatcher | None = None
    if embeddings_client is not None:
        candidate = PrototypeMatcher(
            embeddings_client, model_name=settings.OLLAMA_EMBEDDING_MODEL
        )
        prototype_matcher = candidate if candidate.available else None

    async def planning_node(
        state: PlanningState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Resolve the execution plan. Sub-millisecond in the common case."""
        await emit_node_start(
            config, "planning", "Planlama", "İş planı hazırlanıyor..."
        )

        decision = await resolve_plan(
            state["input_text"],
            state.get("document_id"),
            intent_client,
            previous_intent=state.get("plan_intent"),
            matcher=prototype_matcher,
            focus=state.get("focus") or SessionFocus(),
        )
        logger.info(
            "Plan: %s (intent=%s, source=%s)",
            decision.steps,
            decision.intent,
            decision.source,
        )

        await emit(
            config,
            {
                "event": "planning_completed",
                "plan_steps": decision.steps,
                "intent": decision.intent,
                "reasoning": decision.reasoning,
                "reasoning_level": state.get("reasoning_level", ReasoningLevel.BALANCED.value),
            },
        )

        run_id = uuid4().hex
        thread_id = (config.get("configurable") or {}).get("thread_id", "")
        await start_run(
            run_id=run_id,
            thread_id=thread_id,
            user_id=state.get("user_id"),
            document_id=state.get("document_id"),
            input_text=state["input_text"],
            intent=decision.intent,
            plan_steps=decision.steps,
            source=decision.source,
            confidence=decision.confidence,
            evidence=decision.evidence,
            alternatives=decision.alternatives,
            clarification=decision.clarification,
        )

        return {
            "run_id": run_id,
            "plan_steps": decision.steps,
            "plan_intent": decision.intent,
            "current_step_idx": 0,
            "_last_ran_step": None,
            "cached_document": _load_cached_document(state.get("document_id")),
            "classification_result": {},
            "draft_result": {},
            "routing_result": {},
            "assist_result": {},
            "revise_result": {},
            "clarify_result": {},
            "final_output": {},
            "history": [{"role": "user", "content": state["input_text"]}],
            # Always written, even to None: a decision of any other kind
            # supersedes and clears a stale open question rather than
            # leaving it to linger once it's no longer what the next reply
            # is actually answering.
            "focus": {"pending_clarification": decision.clarification},
        }

    async def _run_classification(
        state: PlanningState, config: RunnableConfig
    ) -> dict[str, Any]:
        cached = state.get("cached_document") or {}
        if cached.get("analysis"):
            logger.info("Using cached analysis for document %s", state.get("document_id"))
            analysis = cached["analysis"]
            await emit_partial(config, "classification", analysis)
            # The live path's compliance node only ever turns 'running'
            # (derived from classification's own node_start) to 'completed'
            # via this partial_result. The cached path never invokes the
            # analysis sub-graph at all, so without replaying it here, a
            # document analyzed earlier and then drafted from cache left the
            # frontend's 'Uygunluk' node stuck amber forever.
            await emit_partial(
                config,
                "compliance",
                {
                    "compliance_status": analysis.get("compliance_status"),
                    "missing_fields": analysis.get("missing_fields") or [],
                },
            )

            # Likewise replay the "rag" node's own start/end (D1): the live
            # path's retrieve_mevzuat_node now emits these for itself, and the
            # cached path must mirror that so 'Mevzuat' doesn't sit at 'todo'
            # forever -- there is no sub-graph invocation here to emit them.
            mevzuat_references = analysis.get("mevzuat_references") or []
            await emit_node_start(
                config, "rag", "Mevzuat Tarama", "Önbellekteki mevzuat sonuçları yükleniyor..."
            )
            await emit_node_end(
                config,
                "rag",
                "Mevzuat Tarama",
                f"{len(mevzuat_references)} mevzuat alıntısı yüklendi (önbellek).",
                {
                    "search_query": "",
                    "documents": [],
                    "context": "\n\n".join(
                        f"[MEVZUAT] {item.get('mevzuat', '')}: {item.get('aciklama', '')}"
                        for item in mevzuat_references
                        if isinstance(item, dict) and item.get("mevzuat")
                    ),
                },
            )

            await emit_node_end(
                config,
                "classification",
                "Evrak Analizi",
                "Evrak analizi tamamlandı (önbellek).",
                {"mevzuat_suggestions": mevzuat_references},
            )
            return analysis

        return await document_analysis_graph.ainvoke(
            {"input_text": state["input_text"], "is_ocr_text": False},
            config=child_config(config),
        )

    async def _run_draft(
        state: PlanningState, classification: dict[str, Any], config: RunnableConfig
    ) -> dict[str, Any]:
        cached = state.get("cached_document") or {}
        source_document = cached.get("extracted_text") or state["input_text"]

        context = _mevzuat_context(classification)

        return await draft_graph.ainvoke(
            {
                "source_document": source_document,
                "classification": classification,
                "correspondence_type": _requested_correspondence_type(classification),
                "context": context,
                "instructions": (
                    f"Kullanıcı İsteği: {state['input_text']}\n\n"
                    "Gelen evraka, evrakın amacı ve doğrulanmış bağlam doğrultusunda "
                    "resmî ve kurumsal bir Türkçe yanıt taslağı oluştur."
                ),
                "attempts": 0,
                "reasoning_level": state.get("reasoning_level", ReasoningLevel.BALANCED.value),
            },
            config=child_config(config),
        )

    async def _run_assist(
        state: PlanningState, classification: dict[str, Any], config: RunnableConfig
    ) -> dict[str, Any]:
        """Answer conversationally, calling document/legislation tools as needed.

        Replaces the previous ``_run_chat``/``_run_document_qa`` split: which
        of the two a message needed used to be the router's decision (and a
        chunk of ``intent_rules.py``/``intent_scorer.py`` existed only to
        arbitrate it). Here the model decides per-turn via
        ``AssistantAgent.run_stream``'s tool loop -- a document being attached
        only changes which tools exist to call, never which step runs.
        """
        document_id = state.get("document_id")
        cached = state.get("cached_document") or {}
        analysis = classification or cached.get("analysis") or {}

        document_context = "(Bu turda yüklenmiş bir belge yok.)"
        if document_id:
            document_context = (
                f"Bir belge yüklü. Özet: {analysis.get('summary') or 'Özet mevcut değil.'}\n"
                "Detay veya belge içeriği gerekiyorsa ilgili aracı çağır."
            )
        history_summary_text = (
            state.get("history_summary")
            or "(Bu konuşmada henüz özetlenecek eski mesaj yok.)"
        )

        # Everything outside the two blocks below is fixed for this call --
        # the system prompt template and the user's own message -- so it is
        # reserved alongside the completion budget rather than modeled as a
        # block of its own.
        fixed_cost = llm_client.count_tokens(
            assistant_agent.system_prompt
        ) + llm_client.count_tokens(state["input_text"])
        context_budget = TokenBudget(
            total=settings.OLLAMA_NUM_CTX,
            reserved_for_completion=ASSIST_COMPLETION_RESERVE_TOKENS + fixed_cost,
        )

        async def _render_document_context() -> str:
            return document_context

        async def _render_history_summary() -> str:
            return history_summary_text

        assembled = await context_builder.build(
            [
                ContextBlock(
                    id="history_summary",
                    priority=10,
                    render=_render_history_summary,
                    compressor=truncate_with_marker,
                    required=True,
                ),
                ContextBlock(
                    id="document_context",
                    priority=20,
                    render=_render_document_context,
                    compressor=truncate_with_marker,
                    required=True,
                ),
            ],
            context_budget,
        )

        remaining_for_history = context_budget.available - assembled.total_tokens
        history = select_history_window(
            _prior_turns(state, HISTORY_RAW_CAP),
            remaining_for_history,
            llm_client.count_tokens,
            min_turns=2,
            max_turns=HISTORY_WINDOW,
        )
        if assembled.dropped or assembled.compressed or len(history) < len(
            _prior_turns(state, HISTORY_WINDOW)
        ):
            logger.info(
                "Assist context budget: dropped=%s compressed=%s history_turns=%d",
                assembled.dropped,
                assembled.compressed,
                len(history),
            )

        referenced_anchor: dict[str, str] = {}

        def _record_referenced_anchor(anchor: str) -> None:
            referenced_anchor["anchor"] = anchor

        tools = build_assistant_tools(
            document_id=document_id,
            cached_document=cached,
            vector_store=vector_store,
            embeddings_client=embeddings_client,
            qa_sparse_encoder=qa_sparse_encoder,
            qa_result_limit=QA_RESULT_LIMIT,
            rag_graph=rag_graph,
            config=config,
            on_anchor_referenced=_record_referenced_anchor,
        )

        chunks: list[str] = []
        try:
            async with asyncio.timeout(
                node_budget("assist", state.get("reasoning_level"))
            ):
                async for chunk in assistant_agent.run_stream(
                    query=state["input_text"],
                    history=history,
                    history_summary=assembled.get("history_summary"),
                    document_context=assembled.get("document_context"),
                    tools=tools,
                    config=config,
                    node="assist",
                ):
                    chunks.append(chunk)
                    await emit_token(config, "assist", chunk)
            reply, flagged = build_response("".join(chunks).strip())
            result = {
                "reply": reply,
                "status": StepStatus.COMPLETED,
                "history": [{"role": "assistant", "content": reply}],
            }
            if flagged:
                result["flagged"] = True
            if referenced_anchor.get("anchor"):
                result["last_referenced_anchor"] = referenced_anchor["anchor"]
            return result
        except asyncio.TimeoutError:
            logger.warning("Assist step timed out")
            return {
                "reply": "Yanıt üretimi zaman aşımına uğradı.",
                "status": StepStatus.FAILED,
            }
        except Exception as exc:
            logger.exception("Assist step failed")
            return {"reply": f"Yanıt üretilemedi: {exc}", "status": StepStatus.FAILED}

    async def focus_node(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        """Update the session's persistent focus from this turn's settled results.

        Runs once per turn, after the executor loop (and human_gate, if it
        ran) finish -- the same timing as consolidate_memory_node and for
        the same reason: it must see the turn's final, settled draft_result,
        not a mid-reflexion-loop snapshot. A separate node rather than folded
        into consolidate_memory_node, which stays focused on its own single
        concern (see its docstring).
        """
        focus = state.get("focus") or SessionFocus()
        update = compute_focus_update(
            focus,
            document_id=state.get("document_id"),
            plan_intent=state.get("plan_intent"),
            input_text=state.get("input_text", ""),
            draft_result=state.get("draft_result") or {},
            assist_result=state.get("assist_result") or {},
        )
        return {"focus": update} if update else {}

    async def consolidate_memory_node(
        state: PlanningState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Fold turns that fell outside the verbatim window into history_summary.

        Runs once per turn, after the executor loop (and human_gate, if it ran)
        finish -- never mid-turn, so it never sees a partially-built response.
        A separate terminal node rather than folded into planning_node, whose
        docstring commits it to staying sub-millisecond (deterministic, no LLM
        call); this node's LLM call is conditional and only ever runs here.

        Also the run-recording audit trail's closing hook (see
        app.observability.run_recorder.end_run): the true last node before
        END (a paused human-in-the-loop run never reaches this node at all --
        its run stays "running" until a resume eventually does).
        """
        final_output = state.get("final_output") or {}
        await end_run(
            run_id=state.get("run_id", ""),
            status=str(final_output.get("status", "unknown")).lower(),
        )

        pending, boundary = _pending_consolidation(
            state.get("history") or [],
            state.get("history_summarized_through", 0),
            HISTORY_WINDOW,
            CONSOLIDATION_BATCH_SIZE,
        )
        if not pending:
            return {}
        try:
            summary = await memory_summarizer_agent.summarize(
                existing_summary=state.get("history_summary") or "", new_turns=pending
            )
            return {"history_summary": summary, "history_summarized_through": boundary}
        except Exception:
            logger.exception("Memory consolidation failed; keeping prior summary")
            return {}

    async def _step_classification(
        state: PlanningState, config: RunnableConfig, classification: dict[str, Any], updates: dict[str, Any]
    ) -> None:
        updates["classification_result"] = await _run_classification(state, config)

    async def _step_draft(
        state: PlanningState, config: RunnableConfig, classification: dict[str, Any], updates: dict[str, Any]
    ) -> None:
        updates["draft_result"] = await _run_draft(state, classification, config)

    async def _step_routing(
        state: PlanningState, config: RunnableConfig, classification: dict[str, Any], updates: dict[str, Any]
    ) -> None:
        draft_result = updates.get("draft_result") or state.get("draft_result") or {}
        score = draft_result.get("confidence_score", 100.0)
        if draft_result.get("requires_human_approval"):
            score = 0.0
        updates["routing_result"] = await routing_graph.ainvoke(
            {"draft": draft_result.get("draft", ""), "confidence_score": score},
            config=child_config(config),
        )

    async def _step_assist(
        state: PlanningState, config: RunnableConfig, classification: dict[str, Any], updates: dict[str, Any]
    ) -> None:
        assist_result = await _run_assist(state, classification, config)
        updates["assist_result"] = assist_result
        # assist_result carries its own "history" entry (the assistant's reply)
        # nested inside it -- it must be hoisted to a top-level update or the
        # history reducer never sees it, and assistant turns silently never
        # make it into checkpointed memory.
        if assist_result.get("history"):
            updates["history"] = assist_result["history"]

    async def _step_revise(
        state: PlanningState, config: RunnableConfig, classification: dict[str, Any], updates: dict[str, Any]
    ) -> None:
        focus = state.get("focus") or SessionFocus()
        active_draft = focus.active_draft
        if active_draft is None:
            # Not reachable through the router today -- revise's own rules
            # only score with an active draft present (see intent_rules.py)
            # -- but a resumed or hand-crafted state could still land here.
            result = {
                "status": StepStatus.FAILED,
                "error": "Revize edilecek aktif bir taslak bulunamadı.",
                "draft": "",
            }
            updates["draft_result"] = result
            # `ready_steps`/`all_steps_settled` (step_graph.py) key readiness
            # on `state[f"{step}_result"]` generically -- "revise" writes its
            # real payload into `draft_result` instead (see `_result_key`
            # below), so it also needs this thin same-status marker or the
            # scheduler never sees the step as having run and the executor
            # loops on it forever.
            updates["revise_result"] = {"status": result["status"]}
            return

        result = await run_revise(
            active_draft=active_draft,
            instructions=state["input_text"],
            correspondence_type=active_draft.correspondence_type,
            llm_client=llm_client,
            fast_llm_client=fast_llm_client,
            reasoning_level=state.get("reasoning_level", ReasoningLevel.BALANCED.value),
            config=config,
            emit_token_fn=emit_token,
        )
        updates["draft_result"] = result
        updates["revise_result"] = {"status": result["status"]}
        # "revise" is in `_execute_one_step`'s completion-skip set (its
        # result lives under draft_result, not revise_result -- see
        # `_result_key`), so unlike assist/routing it must announce its own
        # completion here rather than relying on the generic fallback.
        if result.get("status") != StepStatus.FAILED:
            await emit_node_end(
                config, "revise", "Taslak Revizyonu", "Taslak revizyonu tamamlandı.", result
            )

    async def _step_clarify(
        state: PlanningState, config: RunnableConfig, classification: dict[str, Any], updates: dict[str, Any]
    ) -> None:
        focus = state.get("focus") or SessionFocus()
        pending = focus.pending_clarification or {}
        question = pending.get("question") or "Bu isteğinizi biraz açar mısınız?"
        updates["assist_result"] = {"reply": question, "status": StepStatus.COMPLETED}
        # Same reason as _step_revise's marker: the scheduler keys readiness
        # on `clarify_result`, not on the `assist_result` key this step's
        # actual payload lives in.
        updates["clarify_result"] = {"status": StepStatus.COMPLETED}

    #: One entry per dispatchable step name. Each runner reads whatever it
    #: needs from `state`/`classification` and writes its result(s) directly
    #: into `updates` -- the same contract the old `if/elif` chain's branches
    #: had, just each in its own callable instead of sharing one function body.
    #: A step absent here (there is none today) falls through to the
    #: "unknown step" branch in `execute_step_node`, exactly as before.
    STEP_RUNNERS: dict[
        str, Callable[[PlanningState, RunnableConfig, dict[str, Any], dict[str, Any]], Awaitable[None]]
    ] = {
        "classification": _step_classification,
        "draft": _step_draft,
        "routing": _step_routing,
        "assist": _step_assist,
        "revise": _step_revise,
        "clarify": _step_clarify,
    }

    def _result_key(step: str) -> str:
        """The `updates` key a step's own result lives under.

        `f"{step}_result"` for every step except the two that deliberately
        write into an existing key instead of a new one of their own: revise
        updates `draft_result` (so human_gate/routing/focus_node's
        versioning treat a revision exactly like a fresh draft, see
        `app.ai.workflows.revise`), and clarify updates `assist_result` (its
        question is surfaced through the same "reply" plumbing as an
        ordinary conversational answer).
        """
        return {"revise": "draft_result", "clarify": "assist_result"}.get(
            step, f"{step}_result"
        )

    def _mark_step_result(updates: dict[str, Any], step: str, payload: dict[str, Any]) -> None:
        """Record a generic (skipped/failed) outcome for `step`.

        Always writes `f"{step}_result"`: `ready_steps`/`all_steps_settled`
        (step_graph.py) key readiness on that name for every step uniformly,
        regardless of where a *successful* run's richer payload ends up (see
        `_result_key`) -- a step whose runner never got to write its own
        marker (raised before doing so, or was skipped outright) must still
        settle here, or the executor loops on it forever.
        """
        updates[f"{step}_result"] = payload
        payload_key = _result_key(step)
        if payload_key != f"{step}_result":
            updates.setdefault(payload_key, payload)

    async def _execute_one_step(
        state: PlanningState, config: RunnableConfig, step: str
    ) -> dict[str, Any]:
        """Run exactly one plan step and return its own partial state update.

        Everything `execute_step_node` used to do inline for the single step
        at `current_step_idx` -- cache-seeding, the dependency skip-gate,
        dispatch, event emission -- unchanged behaviourally. Split into its
        own coroutine so a `parallel_safe` batch (see `execute_step_node`)
        can run more than one of these concurrently via `asyncio.gather`;
        every plan `PLAN_BY_INTENT` produces today is a linear chain, so in
        practice this still always runs one at a time, sequentially.
        """
        label = STEP_LABELS.get(step, step.capitalize())
        updates: dict[str, Any] = {}
        cached = state.get("cached_document") or {}

        # Seed the classification from cache when the plan skips the analysis
        # step but a later step needs its output. Written into the returned
        # update rather than assigned onto `state`, which LangGraph does not
        # support and which silently lost the value on the next superstep.
        classification = state.get("classification_result") or {}
        if not classification and cached.get("analysis"):
            classification = cached["analysis"]
            updates["classification_result"] = classification

        failed_dependency = _dependency_failed(step, state, updates)
        if failed_dependency is not None:
            reason = (
                f"'{STEP_LABELS.get(failed_dependency, failed_dependency)}' adımı "
                "başarısız olduğu için bu adım atlandı."
            )
            logger.warning("Skipping plan step '%s': %s", step, reason)
            await emit_node_skipped(config, step, label, reason)
            _mark_step_result(updates, step, {"status": StepStatus.SKIPPED, "reason": reason})
            return updates

        await emit_node_start(
            config, step, label, STEP_MESSAGES.get(step, f"{label} yürütülüyor...")
        )

        started = time.perf_counter()
        try:
            runner = STEP_RUNNERS.get(step)
            if runner is not None:
                await runner(state, config, classification, updates)
            else:
                logger.warning("Unknown workflow step skipped: %s", step)

        except (asyncio.CancelledError, GraphInterrupt):
            # A client disconnect or an interrupt() call anywhere in this
            # node's call tree must propagate, not be swallowed into a FAILED
            # result -- either would otherwise look exactly like an ordinary
            # step failure to the rest of the graph. No sub-graph calls
            # interrupt() today, but this node has a checkpointer attached
            # once one is configured, so a future one must not be silently
            # eaten here. Also why the batch below never uses
            # `asyncio.gather(..., return_exceptions=True)`: that would box
            # this exception alongside an ordinary step failure instead of
            # letting it propagate.
            raise
        except Exception as exc:
            logger.exception("Plan step '%s' failed", step)
            _mark_step_result(updates, step, {"status": StepStatus.FAILED, "error": str(exc)})
            await emit_node_error(
                config, step, label, f"{label} sırasında bir hata oluştu.", detail=str(exc)
            )

        step_status = updates.get(_result_key(step), {}).get("status")
        step_duration = time.perf_counter() - started
        step_outcome = "failed" if step_status == StepStatus.FAILED else "completed"
        NODE_DURATION.labels(
            graph="planning", node=step, status=step_outcome
        ).observe(step_duration)
        await record_step(
            run_id=state.get("run_id", ""),
            step=step,
            status=step_outcome,
            duration_ms=step_duration * 1000,
            error=updates.get(_result_key(step), {}).get("error"),
        )

        # The sub-graphs emit their own node_end events with richer payloads;
        # only announce completion here for steps that have none, and only
        # when the step didn't already report itself via emit_node_error above.
        if step in {"classification", "draft", "routing", "revise"}:
            pass
        elif updates.get(_result_key(step), {}).get("status") == StepStatus.FAILED:
            pass
        else:
            await emit_node_end(
                config, step, label, f"{label} tamamlandı.", updates.get(_result_key(step), {})
            )

        return updates

    async def execute_step_node(
        state: PlanningState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Run every currently-ready plan step and advance the turn counter.

        Readiness (`ready_steps`) replaces the old `current_step_idx`-based
        array indexing -- a step runs once its in-plan dependencies have,
        regardless of position. With no `StepSpec` marked `parallel_safe`
        today, `batch` is always a single step, so this reproduces the old
        strictly-linear order exactly; the multi-step branch exists for a
        future step type that genuinely doesn't touch an LLM (see
        `step_graph.ready_steps`'s docstring for why none does yet).
        """
        steps = state.get("plan_steps") or []
        if all_steps_settled(steps, state):
            return {}

        ready = ready_steps(steps, state)
        if not ready:
            # Not reachable by any PLAN_BY_INTENT combination today -- would
            # mean a cycle or an unsatisfiable dependency in STEP_SPECS.
            # Ending the turn here rather than looping forever if it ever is.
            logger.error("No plan step is ready but the plan is not settled: %s", steps)
            return {}

        parallel_batch = [
            name for name in ready if STEP_SPECS.get(name, StepSpec(name=name)).parallel_safe
        ]
        batch = parallel_batch if len(parallel_batch) > 1 else ready[:1]

        idx = state.get("current_step_idx", 0)
        logger.info(
            "Executing plan step(s) %d-%d/%d: %s", idx + 1, idx + len(batch), len(steps), batch
        )

        if len(batch) > 1:
            partials = await asyncio.gather(
                *(_execute_one_step(state, config, name) for name in batch)
            )
        else:
            partials = [await _execute_one_step(state, config, batch[0])]

        merged: dict[str, Any] = {"current_step_idx": idx + len(batch), "_last_ran_step": batch[-1]}
        for partial in partials:
            merged.update(partial)

        if all_steps_settled(steps, {**state, **merged}):
            merged["final_output"] = _compile_final_output(state, merged)

        return merged

    def _compile_final_output(
        state: PlanningState, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Assemble the response payload from state plus this step's updates."""

        def _pick(key: str) -> dict[str, Any]:
            return updates.get(key) or state.get(key) or {}

        draft_result = _pick("draft_result")
        draft_status = draft_result.get("status")
        final_status = (
            draft_status
            if draft_status
            in {
                StepStatus.FAILED,
                StepStatus.NEEDS_HUMAN_APPROVAL,
                StepStatus.NEEDS_INPUT,
                StepStatus.REVISE_REQUESTED,
                StepStatus.REJECTED,
            }
            else StepStatus.COMPLETED
        )

        return {
            "status": final_status,
            "classification": _pick("classification_result"),
            "draft": draft_result,
            "routing": _pick("routing_result"),
            "assist": _pick("assist_result"),
        }

    async def human_gate_node(
        state: PlanningState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Pause the run for a human answer, then apply it without regenerating.

        A separate node from ``executor`` on purpose: ``interrupt()`` replays
        its own node from the top on resume. Living here, resuming replays a
        few dict lookups; living inside ``execute_step_node`` (which is where
        the draft step itself runs), resuming would replay the entire ~30s
        draft generation the executor already committed to state.
        """
        draft_result = state.get("draft_result") or {}
        missing_information = draft_result.get("missing_information") or []
        kind = "missing_information" if missing_information else "draft_approval"

        payload = {
            "kind": kind,
            "questions": missing_information,
            "draft": draft_result.get("draft", ""),
            "verification": draft_result.get("verification", {}),
            "judge": draft_result.get("judge", {}),
            "combined_score": draft_result.get("combined_score"),
            "requires_human_approval": draft_result.get("requires_human_approval"),
        }
        # Deterministic, not a fresh uuid4: interrupt() re-executes everything
        # before it on resume, including this id's computation, and it must
        # come out identical both times for the frontend's dedup to work.
        interrupt_id = hashlib.sha256(
            f"{kind}:{draft_result.get('draft', '')}:{state.get('current_step_idx', 0)}".encode(
                "utf-8"
            )
        ).hexdigest()[:16]

        HITL_INTERRUPTS.labels(kind=kind).inc()
        await emit_node_start(
            config,
            "human_gate",
            "İnsan Onayı",
            "Devam etmek için insan onayı/eksik bilgi bekleniyor...",
        )
        await emit_interrupt(config, kind=kind, interrupt_id=interrupt_id, payload=payload)
        answer = interrupt(payload)
        answer = answer if isinstance(answer, dict) else {}
        # Execution only reaches here after Command(resume=...) -- the gate is
        # now resolved, whatever the human decided.
        await emit_node_end(
            config, "human_gate", "İnsan Onayı", "İnsan yanıtı alındı, işleme devam ediliyor.", answer
        )

        if kind == "missing_information":
            filled_draft, residual = apply_answers(
                draft_result.get("draft", ""), answer.get("answers", {})
            )

            if residual:
                residual_questions = [
                    question
                    for question in missing_information
                    if question.get("key") in residual
                ]
                updated = {
                    **draft_result,
                    "draft": filled_draft,
                    "missing_information": residual_questions,
                    "status": StepStatus.NEEDS_INPUT,
                }
                return {"draft_result": updated}

            report = verify_draft(
                filled_draft,
                source_document=draft_result.get("source_document", ""),
                context=draft_result.get("context", ""),
                classification=draft_result.get("classification") or {},
                instructions=draft_result.get("instructions", ""),
                strict=draft_result.get("correspondence_type") != "other_official",
            )
            status = StepStatus.NEEDS_HUMAN_APPROVAL if report.requires_human_approval else StepStatus.COMPLETED
            updated = {
                **draft_result,
                "draft": filled_draft,
                "confidence_score": report.confidence_score,
                "combined_score": report.confidence_score,
                "requires_human_approval": report.requires_human_approval,
                "verification": report.model_dump(),
                "evaluation_notes": report.evaluation_notes,
                "missing_information": [],
                "status": status,
            }
            return {"draft_result": updated}

        # draft_approval
        action = answer.get("action")
        if action == "revise":
            note = (answer.get("instructions") or "").strip()
            existing = draft_result.get("instructions", "")
            updated = {
                **draft_result,
                "instructions": f"{existing}\n\nEk talimat (insan geri bildirimi): {note}".strip(),
                "status": StepStatus.REVISE_REQUESTED,
            }
            updates = {"draft_result": updated}
            # A resume may ask for a different reasoning level on the retry
            # (e.g. escalate to "deep" after a "fast" draft was rejected).
            # Omitted -> state's existing reasoning_level is left untouched.
            if answer.get("reasoning_level"):
                updates["reasoning_level"] = answer["reasoning_level"]
            updates["final_output"] = _compile_final_output(state, updates)
            return updates

        if action == "reject":
            updated = {**draft_result, "status": StepStatus.REJECTED}
            updates = {"draft_result": updated}
            updates["final_output"] = _compile_final_output(state, updates)
            return updates

        # Default: approve. Falls through to routing via route_after_gate.
        updated = {
            **draft_result,
            "status": StepStatus.APPROVED,
            "approved_by": answer.get("user_id"),
        }
        return {"draft_result": updated}

    def route_after_step(state: PlanningState) -> str:
        steps = state.get("plan_steps") or []

        if has_checkpointer and state.get("_last_ran_step") in {"draft", "revise"}:
            draft_result = state.get("draft_result") or {}
            draft_status = draft_result.get("status")
            if draft_status == StepStatus.NEEDS_INPUT:
                return "human_gate"
            if (
                draft_status == StepStatus.NEEDS_HUMAN_APPROVAL
                and settings.HITL_APPROVAL_GATE_ENABLED
            ):
                return "human_gate"

        return "end" if all_steps_settled(steps, state) else "continue"

    def route_after_gate(state: PlanningState) -> str:
        draft_result = state.get("draft_result") or {}
        status = draft_result.get("status")
        if status == StepStatus.NEEDS_INPUT:
            return "human_gate"
        if status in {StepStatus.REVISE_REQUESTED, StepStatus.REJECTED}:
            return "end"
        return "continue"

    builder = StateGraph(PlanningState)
    builder.add_node("planning", planning_node)
    builder.add_node("executor", execute_step_node)
    builder.add_node("human_gate", human_gate_node)
    builder.add_node("focus", focus_node)
    builder.add_node("consolidate_memory", consolidate_memory_node)

    builder.add_edge(START, "planning")
    builder.add_edge("planning", "executor")
    builder.add_conditional_edges(
        "executor",
        route_after_step,
        {"continue": "executor", "human_gate": "human_gate", "end": "focus"},
    )
    builder.add_conditional_edges(
        "human_gate",
        route_after_gate,
        {"human_gate": "human_gate", "continue": "executor", "end": "focus"},
    )
    builder.add_edge("focus", "consolidate_memory")
    builder.add_edge("consolidate_memory", END)

    return builder.compile(checkpointer=checkpointer)
