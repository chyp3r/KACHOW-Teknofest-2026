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
from app.ai.agents.guardrail_judge import GuardrailJudgeAgent
from app.ai.agents.memory_summarizer import MemorySummarizerAgent
from app.ai.context import ContextBlock, ContextBuilder, TokenBudget, select_history_window
from app.ai.context.compress import truncate_with_marker
from app.ai.embeddings.models import BaseEmbeddingsClient
from app.ai.guardrails.llm_nuance import judge_output_leakage
from app.ai.guardrails.output_gate import classify_reason_kind, evaluate_response
from app.ai.guardrails.sensitivity import SensitivityAssessment, assessment_from_analysis
from app.ai.session.focus import DraftVersion, SessionFocus, compute_focus_update, merge_focus
from app.ai.llms.base import BaseLLMClient
from app.ai.policy import get_policy
from app.ai.policy.budget import node_budget
from app.ai.retrieval.sparse_encoder import SparseBM25Encoder
from app.ai.semantic.prototype_matcher import PrototypeMatcher
from app.ai.tools.document_tools import ToolResult, build_assistant_tools
from app.ai.tools.transfer_tools import build_transfer_tools
from app.ai.verification import InfoQuestion, apply_answers, verify_draft
from app.ai.workflows.events import (
    child_config,
    emit,
    emit_guardrail_event,
    emit_interrupt,
    emit_node_end,
    emit_node_error,
    emit_node_skipped,
    emit_node_start,
    emit_notice,
    emit_partial,
    emit_question,
)
from app.ai.workflows.dates import today_tr
from app.ai.workflows.intent_rules import RESET_SURFACES
from app.ai.workflows.intent_scorer import normalize
from app.ai.workflows.planner import resolve_plan
from app.ai.workflows.relevance import build_unrelated_reply, resolve_relevance
from app.ai.workflows.revise import run_revise
from app.ai.workflows.scope import build_refusal_reply
from app.ai.workflows.revise_graph import create_revise_graph
from app.ai.workflows.step_graph import STEP_SPECS, StepSpec, all_steps_settled, ready_steps
from app.ai.workflows.writing_brief import AUTO_ANSWER, resolve_brief
from app.core.config import settings
from app.core.enums.reasoning_level import ReasoningLevel
from app.core.enums.sensitivity_level import SensitivityLevel
from app.core.enums.step_status import StepStatus
from app.infrastructure.vectorstore.base import BaseVectorStore
from app.observability import guardrail_recorder
from app.observability.ai_metrics import (
    HITL_INTERRUPTS,
    NODE_DURATION,
    ROUTER_CONFIDENCE,
    ROUTER_DECISIONS,
    ROUTER_SEMANTIC_AVAILABLE,
)
from app.observability.run_recorder import end_run, record_step, start_run

logger = logging.getLogger(__name__)

QA_RESULT_LIMIT = get_policy().memory.qa_result_limit

STEP_LABELS = {
    "classification": "Evrak Analizi",
    "brief": "Yazım Briefi",
    "draft": "Taslak Oluşturma",
    "routing": "Birim Yönlendirme",
    "assist": "Asistan",
    "revise": "Taslak Revizyonu",
    "clarify": "Açıklayıcı Soru",
    "refuse": "Kapsam Denetimi",
    "gate_revise": "Geri Bildirimli Revizyon",
    "transfer_execute": "Transfer Gönderiliyor",
    "transfer_gate": "Transfer Onayı",
}

STEP_MESSAGES = {
    "classification": "Belge sınıflandırılıyor ve üst veriler çıkarılıyor...",
    "brief": "Taslak öncesi yazım briefi hazırlanıyor...",
    "draft": "Resmî cevap taslağı hazırlanıyor...",
    "routing": "Cevap taslağının iletileceği birim analiz ediliyor...",
    "assist": "Asistan yanıtı hazırlanıyor...",
    "revise": "Taslak talebe göre güncelleniyor...",
    "clarify": "İsteğinizi netleştirmek için bir soru hazırlanıyor...",
    "refuse": "İstek sistemin görev alanına göre denetleniyor...",
    "gate_revise": "Onay kapısındaki geri bildiriminize göre taslak güncelleniyor...",
    "transfer_execute": "Transfer gönderiliyor...",
}

def _dependency_failed(
    step: str, state: "PlanningState", updates: dict[str, Any]
) -> Optional[str]:
    """Return the name of a failed-or-skipped dependency for ``step``, if any.

    A step whose dependency's own result carries status FAILED must not run
    on empty/garbage input. Without this a failed draft still let routing
    run on draft="" and route to human approval -- an outcome visually
    identical to a real routing decision. The dependency edges themselves
    live in ``step_graph.STEP_SPECS`` (shared with ``ready_steps``); this
    function is the other half -- *whether a failure* should skip the step,
    which is deliberately not `ready_steps`'s concern (see its docstring).

    SKIPPED counts the same as FAILED here: a dependency that decided not to
    produce output (e.g. ``_step_draft`` refusing an off-topic request via
    ``app.ai.workflows.relevance``) leaves nothing for a dependent step to
    run on either, even though nothing actually errored.

    Args:
        step: The plan step about to run.
        state: The graph state as of the start of this superstep.
        updates: Updates already computed earlier in this same superstep
            (a dependency that just ran this turn is not yet in ``state``).

    Returns:
        The failed/skipped dependency's step name, or None when every
        dependency (if any) settled successfully or has not run yet.
    """
    spec = STEP_SPECS.get(step, StepSpec(name=step))
    for dependency in spec.depends_on:
        result = updates.get(f"{dependency}_result") or state.get(f"{dependency}_result") or {}
        if result.get("status") in (StepStatus.FAILED, StepStatus.SKIPPED):
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

#: `plan_evidence` ids that mark a turn as plain small talk -- see
#: `_run_assist`'s `is_small_talk_turn`.
_SMALL_TALK_EVIDENCE = frozenset({"assist.greeting", "assist.courtesy", "assist.farewell"})

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
    #: ChatService._invoke). None in the open demo/dev path. Read by the
    #: run-recording hooks in this module and, alongside
    #: requester_clearance below, by _run_assist's tool/output-gate wiring.
    user_id: str | None
    #: The authenticated caller's tenant (ChatService._invoke), carried the
    #: same way user_id is -- read by every recorder call in this module
    #: (start_run/record_step/end_run, the output guardrail's
    #: record_event) so their writes can be attributed to a company, and by
    #: the routing sub-call (see routing_node) to scope which units it may
    #: suggest. Survives a human-in-the-loop pause/resume via the
    #: checkpointer, same as user_id.
    company_id: str | None
    #: The authenticated caller's resolved SensitivityLevel (see
    #: app.core.permissions.role_checker.clearance_for), as its string
    #: value -- graph state must stay JSON-serialisable, same reason
    #: reasoning_level is stored as .value rather than the enum itself.
    #: None in the open demo/dev path (REQUIRE_AUTH off); _run_assist and
    #: build_assistant_tools both treat that as "skip the clearance check"
    #: per their own docstrings, not "clears nothing" -- output_gate.py's
    #: own requester_clearance handling is the one place None still means
    #: fail-secure.
    requester_clearance: str | None
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
    #: Ids of the lexical rules that fired for this turn's decision (see
    #: `PlanDecision.evidence`). Turn-scoped, like `plan_intent` itself --
    #: reset every turn in `planning_node`. `_run_assist` reads it to tell a
    #: message that resolved to `assist` *because* it looked like a greeting
    #: or a farewell apart from one that landed there for any other reason
    #: (a genuine question, an out-of-scope request), which needs its full
    #: conversational context and must not be treated the same way.
    plan_evidence: tuple[str, ...]
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
    #: Deterministic pre-draft writing-style resolution -- see
    #: app.ai.workflows.writing_brief. `{"status", "answers", "resolved",
    #: "questions"}`; `answers` is what draft_graph._build_brief renders.
    #: Reset every turn in planning_node, unlike focus.writing_brief (its
    #: session-scoped carry-forward).
    brief_result: dict[str, Any]
    #: How many rounds brief_gate_node has re-asked this turn -- plays the
    #: same role gate_revision_count plays for human_gate_node's hash: a
    #: re-ask after a blank required answer must not collide with round 0's
    #: interrupt_id.
    brief_gate_round: int
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
    #: Same arrangement as clarify: the out-of-scope refusal's real payload
    #: goes into assist_result (it is a reply like any other), and this field
    #: exists only so the scheduler can see the step settle.
    refuse_result: dict[str, Any]
    #: A pending transfer proposal, when the assist step's own
    #: `propose_transfer` tool call produced one this turn (see
    #: `app.ai.tools.transfer_tools.build_transfer_tools`, wired into
    #: `_run_assist`) -- deterministic recipient/artifact resolution +
    #: policy check, never the execution itself. `outcome` is one of
    #: `"unresolved"`, `"recipient_not_found"`, `"artifact_ambiguous"`,
    #: `"policy_denied"` (all terminal, no gate -- the tool's own return
    #: string already told the user), `"needs_disambiguation"`/
    #: `"needs_confirmation"` (routed to `transfer_gate_node` by
    #: `route_after_step`), or `"confirmed"` (set by `transfer_gate_node`
    #: once the human approves, routing to `transfer_execute` via
    #: `route_after_transfer_gate`). See the plan's §I for the full
    #: `artifact_transfer_intents.state` lifecycle this outcome tracks a
    #: turn-scoped view of.
    transfer_resolve_result: dict[str, Any]
    #: `_step_transfer_execute`'s outcome -- set only after
    #: `transfer_gate_node` reaches `"confirmed"`. Also the scheduler's
    #: settlement marker for every terminal-without-execution path above
    #: (`{"status": SKIPPED, ...}`), the same dual role `revise_result`/
    #: `clarify_result`/`refuse_result` play for their own steps.
    transfer_execute_result: dict[str, Any]
    #: How many interrupt rounds `transfer_gate_node` has shown this turn --
    #: plays the same role `brief_gate_round`/`gate_revision_count` play for
    #: their own gates: a disambiguation round followed by a confirmation
    #: round must not collide on the same deterministic `interrupt_id`.
    transfer_gate_round: int
    final_output: dict[str, Any]
    #: How many times the human approval gate's own "revizyon iste" action
    #: has re-run the revise sub-graph *within this turn* (see
    #: gate_revise_node/route_after_gate). Reset to 0 every turn in
    #: planning_node, bounded by settings.HITL_MAX_GATE_REVISIONS.
    gate_revision_count: int
    #: The human's typed revision note from the gate's most recent
    #: "revizyon iste" click, consumed by gate_revise_node and cleared
    #: immediately after -- never read anywhere else.
    gate_revision_note: str
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


def _summarize_step_outcome(
    plan_intent: Optional[str],
    draft_result: dict[str, Any],
    assist_result: dict[str, Any],
    classification_result: dict[str, Any],
) -> Optional[str]:
    """One short, honest sentence recording what a non-assist step did.

    ``_run_assist`` appends its own reply to ``history`` already. Every other
    step -- draft, revise, analyze, clarify -- settles a result the user sees
    in ``final_output`` but that never reaches ``history`` or
    ``history_summary``. A later turn that only has the summary to go on then
    sees nothing but the *user's own request text* ("bu taslağı kısalt") with
    no record of what actually happened to it -- and nothing to contradict a
    plausible-sounding but false claim that it succeeded. This closes that
    gap with a status marker, not the full draft text (already retained in
    ``SessionFocus.draft_history`` for anything that needs the real content).

    Args:
        plan_intent: This turn's resolved intent.
        draft_result: This turn's settled ``draft_result``.
        assist_result: This turn's settled ``assist_result`` (carries
            ``clarify``'s question -- see ``_step_clarify``).
        classification_result: This turn's settled ``classification_result``.

    Returns:
        A short assistant-role note, or None for ``assist`` (already
        self-recorded) and for an intent with nothing settled yet.
    """
    if plan_intent in (None, "assist"):
        return None

    if plan_intent in ("draft", "revise"):
        status = draft_result.get("status")
        label = "Taslak" if plan_intent == "draft" else "Taslak revizyonu"
        if status in (
            StepStatus.COMPLETED,
            StepStatus.NEEDS_HUMAN_APPROVAL,
            StepStatus.APPROVED,
        ):
            return f"[Sistem notu] {label} başarıyla hazırlandı (durum: {status})."
        if status == StepStatus.NEEDS_INPUT:
            return f"[Sistem notu] {label} için kullanıcıdan ek bilgi istendi, henüz tamamlanmadı."
        if status == StepStatus.FAILED:
            error = draft_result.get("error") or "bilinmeyen bir hata"
            return f"[Sistem notu] {label} başarısız oldu: {error}"
        if status == StepStatus.REJECTED:
            reason = draft_result.get("rejection_reason")
            return (
                f"[Sistem notu] {label} reddedildi (gerekçe: {reason})."
                if reason
                else f"[Sistem notu] {label} reddedildi."
            )
        return None

    if plan_intent == "analyze":
        doc_type = classification_result.get("correspondence_type") or classification_result.get(
            "type"
        )
        suffix = f" (tür: {doc_type})" if doc_type else ""
        return f"[Sistem notu] Evrak analiz edildi{suffix}."

    if plan_intent == "clarify":
        question = assist_result.get("reply")
        return f'[Sistem notu] Kullanıcıya açıklayıcı bir soru soruldu: "{question}"' if question else None

    return None


#: Turkish labels for SensitivityLevel, for the prompt-facing note only --
#: the enum's own .value (e.g. "cok_gizli") is what every deterministic
#: check compares against, this is purely what the model reads.
_SENSITIVITY_LABELS: dict[SensitivityLevel, str] = {
    SensitivityLevel.UNMARKED: "İşaretlenmemiş",
    SensitivityLevel.TASNIF_DISI: "Tasnif Dışı",
    SensitivityLevel.HIZMETE_OZEL: "Hizmete Özel",
    SensitivityLevel.OZEL: "Özel",
    SensitivityLevel.GIZLI: "Gizli",
    SensitivityLevel.COK_GIZLI: "Çok Gizli",
}


def _build_security_boundary_note(
    sensitivity: Optional[SensitivityAssessment],
    requester_clearance: Optional[SensitivityLevel],
) -> str:
    """Compose the Turkish note rendered into the assistant's system prompt.

    A secondary, prompt-level layer only (see ``assistant.md``'s own
    disclaimer to that effect) -- ``document_tools.py``'s deny-at-retrieval
    check and ``output_gate.py`` are what actually enforce the boundary;
    this exists to catch a paraphrase-around-the-facts case neither of those
    regex/pattern-based checks can see, the same reasoning behind the
    guardrail judge (``app.ai.guardrails.llm_nuance``).

    Args:
        sensitivity: This turn's attached document's assessment, or None
            when no document is attached.
        requester_clearance: The requester's resolved clearance, or None
            when unknown (unauthenticated / REQUIRE_AUTH off).

    Returns:
        The note text. Never empty -- always states what's actually known,
        even when that's "nothing."
    """
    clearance_label = (
        _SENSITIVITY_LABELS.get(requester_clearance, requester_clearance.value)
        if requester_clearance is not None
        else "bilinmiyor (kimlik doğrulaması yok)"
    )
    parts = [f"Bu oturumdaki istek sahibinin yetki seviyesi: {clearance_label}."]

    if sensitivity is not None:
        document_label = _SENSITIVITY_LABELS.get(sensitivity.level, sensitivity.level.value)
        parts.append(f"Bu turda ekli belgenin gizlilik derecesi: {document_label}.")

    return " ".join(parts)


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
    mevzuat_retriever: Any = None,
    adapter_provider: Any = None,
    transfer_provider: Any = None,
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
        mevzuat_retriever: Optional retriever handed to the revise
            sub-graph for conditional legislation re-retrieval (see
            ``app.ai.revision.retrieval``). None always skips it.
        adapter_provider: Optional async callable resolving a company's
            runtime style adapter (Faz C2, see
            ``app.domains.companies.provider.get_company_adapter``) --
            forwarded to the revise sub-graph built below; ``draft_graph``
            gets its own copy at construction time (see
            ``app.api.dependency.get_draft_graph``), not through here. None
            always skips adapter resolution.
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
        transfer_provider: Optional object exposing the `TransferGraphProvider`
            surface (`app.domains.transfers.provider`) -- resolution,
            recipient lookup/recommendation, and the intent state machine's
            transitions, each opening its own session per call, the same
            injected-callable pattern `adapter_provider`/`units_provider`
            already use. Reached only from the assist step's own
            `propose_transfer` tool (`app.ai.tools.transfer_tools`), never
            from a dedicated plan step -- transfer is not a resolvable
            intent (see `planner.PLAN_BY_INTENT`'s own docstring). `None`
            (the default, matching `settings.AI_TRANSFER_ENABLED`'s own
            default) means the tool is simply never offered to the model --
            degraded, not broken, same as an absent `checkpointer`.

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
    # Fast tier, same as the draft path's JudgeAgent: emits a label-sized
    # verdict, not reply text, so the quality tier buys nothing here.
    guardrail_judge_agent = GuardrailJudgeAgent(intent_client)
    # Unfit on purpose, same as the indexing side (documents/service.py):
    # its sparse indices are corpus-independent CRC32 hashes, and query-side
    # IDF weights default to a uniform 1.0 without a fitted vocabulary, which
    # is still a meaningful lexical signal for RRF fusion against the dense
    # vector.
    qa_sparse_encoder = SparseBM25Encoder()

    # Built once per graph, like draft_graph/routing_graph -- run_revise
    # (both the plain "revise" step and the human approval gate's own
    # "revizyon iste" loop, see gate_revise_node) invokes this compiled
    # sub-graph rather than building a fresh one per call.
    revise_graph = create_revise_graph(
        llm_client, fast_llm_client, mevzuat_retriever, adapter_provider
    )

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

    ROUTER_SEMANTIC_AVAILABLE.set(1.0 if prototype_matcher is not None else 0.0)
    if prototype_matcher is None:
        # Not a warning: every message the lexical layer abstains on skips
        # straight past the semantic rung until someone notices and reruns
        # scripts/build_prototypes.py. See ROUTER_SEMANTIC_AVAILABLE's
        # docstring for why this must be loud rather than logged and forgotten.
        logger.error(
            "Semantic intent layer unavailable (missing or stale prototype "
            "vectors) -- every lexically-abstained message will skip straight "
            "to the model/clarify fallback. Run scripts/build_prototypes.py."
        )

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
            # The current turn is appended to `history` only after this node
            # returns (see the `"history"` key below), so what's here is
            # already exactly the prior turns -- no trailing duplicate to
            # drop, unlike `_prior_turns`'s assumption for the assist step.
            history=state.get("history"),
        )
        logger.info(
            "Plan: %s (intent=%s, source=%s)",
            decision.steps,
            decision.intent,
            decision.source,
        )
        ROUTER_DECISIONS.labels(intent=decision.intent, source=decision.source).inc()
        ROUTER_CONFIDENCE.labels(source=decision.source).observe(decision.confidence)

        await emit(
            config,
            {
                "event": "planning_completed",
                "plan_steps": decision.steps,
                "intent": decision.intent,
                "reasoning": decision.reasoning,
                "reasoning_level": state.get("reasoning_level", ReasoningLevel.BALANCED.value),
                "source": decision.source,
                "confidence": decision.confidence,
                "alternatives": list(decision.alternatives),
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
            company_id=state.get("company_id"),
        )

        return {
            "run_id": run_id,
            "plan_steps": decision.steps,
            "plan_intent": decision.intent,
            "plan_evidence": decision.evidence,
            "current_step_idx": 0,
            "_last_ran_step": None,
            "cached_document": _load_cached_document(state.get("document_id")),
            "classification_result": {},
            "brief_result": {},
            "brief_gate_round": 0,
            "draft_result": {},
            "routing_result": {},
            "assist_result": {},
            "revise_result": {},
            "clarify_result": {},
            "refuse_result": {},
            "transfer_resolve_result": {},
            "transfer_execute_result": {},
            "transfer_gate_round": 0,
            "final_output": {},
            "gate_revision_count": 0,
            "gate_revision_note": "",
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

        # The brief gate's own "Yazışma türü" slot (priority 0, see
        # app.ai.workflows.writing_brief.SLOT_CATALOG) is the most explicit
        # signal available -- either the user's own words matched a genre
        # surface, or a human confirmed it at the gate. AUTO_ANSWER means
        # "let the system decide", not "response_letter", so it falls
        # through to classification the same as an unset brief.
        brief_answers = (state.get("brief_result") or {}).get("answers") or {}
        brief_correspondence_type = brief_answers.get("yazisma_turu")
        requested_correspondence_type = (
            brief_correspondence_type
            if brief_correspondence_type and brief_correspondence_type != AUTO_ANSWER
            else _requested_correspondence_type(classification)
        )

        return await draft_graph.ainvoke(
            {
                "source_document": source_document,
                "classification": classification,
                # The user's own message, never the boilerplate below --
                # see draft_graph.validate_input_node / resolve_correspondence_type.
                "user_request": state["input_text"],
                "correspondence_type": requested_correspondence_type,
                "context": context,
                "instructions": (
                    f"Kullanıcı İsteği: {state['input_text']}\n\n"
                    "Gelen evraka, evrakın amacı ve doğrulanmış bağlam doğrultusunda "
                    "resmî ve kurumsal bir Türkçe yanıt taslağı oluştur."
                ),
                "attempts": 0,
                "reasoning_level": state.get("reasoning_level", ReasoningLevel.BALANCED.value),
                "writing_brief": brief_answers,
                "company_id": state.get("company_id") or "",
                "today": today_tr(),
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
        # None (not an UNMARKED assessment) when no document is attached --
        # `output_gate.evaluate_response` treats the two differently: no
        # document means there is nothing to leak, an UNMARKED document
        # means there is a source that was checked and cleared.
        sensitivity = assessment_from_analysis(analysis) if document_id else None
        requester_clearance_raw = state.get("requester_clearance")
        requester_clearance = (
            SensitivityLevel(requester_clearance_raw) if requester_clearance_raw else None
        )
        document_context = "(Bu turda yüklenmiş bir belge yok.)"
        if document_id:
            document_context = (
                f"Bir belge yüklü. Özet: {analysis.get('summary') or 'Özet mevcut değil.'}\n"
                "Detay veya belge içeriği gerekiyorsa ilgili aracı çağır."
            )

        # A message that resolved to `assist` *because* it's plain small talk
        # (a greeting, a courtesy, a sign-off) and nothing else -- not one
        # that merely landed on assist for some other reason, like a genuine
        # question or an out-of-scope request, both of which still need full
        # conversational grounding to answer well. Withholding the rolling
        # summary and the verbatim window here is what stops a bare "selam"
        # from reading prior revise turns and describing them back to the
        # user as if they were relevant to answering it.
        plan_evidence = state.get("plan_evidence") or ()
        is_small_talk_turn = bool(
            _SMALL_TALK_EVIDENCE.intersection(plan_evidence)
        ) and len(state.get("input_text", "").split()) <= 4

        history_summary_text = (
            "(Bu tur küçük bir sohbet ifadesi -- geçmiş özeti bu yanıt için gerekli değil.)"
            if is_small_talk_turn
            else (
                state.get("history_summary")
                or "(Bu konuşmada henüz özetlenecek eski mesaj yok.)"
            )
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
            min_turns=0 if is_small_talk_turn else 2,
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

        tool_outputs: list[ToolResult] = []

        def _record_tool_result(result: ToolResult) -> None:
            tool_outputs.append(result)

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
            on_tool_result=_record_tool_result,
            requester_clearance=requester_clearance,
        )

        # Faz 4 (#201) -- offered only when the feature is actually usable;
        # a message that would have called this tool otherwise resolves
        # exactly like any other conversational turn (the model simply has
        # nothing to call). See app.ai.tools.transfer_tools's own module
        # docstring for why the tool only ever proposes, never executes.
        pending_transfer: dict[str, Any] = {}

        def _record_transfer_proposal(proposal: dict[str, Any]) -> None:
            pending_transfer.update(proposal)

        if settings.AI_TRANSFER_ENABLED and transfer_provider is not None:
            focus = state.get("focus") or SessionFocus()
            tools = [
                *tools,
                *build_transfer_tools(
                    company_id=state.get("company_id"),
                    user_id=state.get("user_id"),
                    thread_id=(config.get("configurable") or {}).get("thread_id", ""),
                    run_id=state.get("run_id"),
                    active_draft_id=focus.active_draft_id,
                    active_document_id=focus.active_document_id,
                    transfer_provider=transfer_provider,
                    on_transfer_proposed=_record_transfer_proposal,
                ),
            ]

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
                    security_boundary=_build_security_boundary_note(
                        sensitivity, requester_clearance
                    ),
                    tools=tools,
                    config=config,
                    node="assist",
                ):
                    chunks.append(chunk)

            raw_reply = "".join(chunks).strip()
            source_materials = "\n\n".join(
                part
                for part in (
                    cached.get("extracted_text", ""),
                    *(tool_output.text for tool_output in tool_outputs),
                )
                if part
            )
            # Only worth asking when a document is attached -- with no
            # source there is nothing for "does this leak the source's
            # meaning" to mean, and the call would just cost latency.
            judge_verdict = None
            if sensitivity is not None:
                judge_verdict = await judge_output_leakage(
                    guardrail_judge_agent,
                    reply=raw_reply,
                    source_summary=analysis.get("summary", ""),
                )

            verdict = evaluate_response(
                raw_reply,
                source_materials=source_materials,
                sensitivity=sensitivity,
                # Resolved above from state["requester_clearance"] (see
                # ChatService._invoke / chat/router.py). Still None in the
                # open demo/dev path (REQUIRE_AUTH off) -- evaluate_response
                # keeps treating that as "unknown clearance", fail-secure,
                # per its own docstring.
                requester_clearance=requester_clearance,
                judge_verdict=judge_verdict,
            )
            reply = verdict.text
            flagged = verdict.action != "pass"

            if flagged:
                guardrail_kind = classify_reason_kind(verdict.reasons)
                guardrail_decision = "blocked" if verdict.action == "block" else "redacted"
                await guardrail_recorder.record_event(
                    stage="output",
                    kind=guardrail_kind,
                    decision=guardrail_decision,
                    reasons=verdict.reasons,
                    run_id=state.get("run_id"),
                    document_id=document_id,
                    company_id=state.get("company_id"),
                    requester_user_id=state.get("user_id"),
                    related_document_ids=[document_id] if document_id else [],
                )
                await emit_guardrail_event(
                    config,
                    stage="output",
                    kind=guardrail_kind,
                    decision=guardrail_decision,
                    reasons=verdict.reasons,
                )

            if pending_transfer.get("outcome") in {"needs_disambiguation", "needs_confirmation"} and not has_checkpointer:
                # Cannot pause for a human answer without a checkpointer --
                # cancel the proposal outright rather than leave it standing
                # unconfirmable, the same degrade every other HITL gate
                # takes (see create_planning_graph's own docstring).
                try:
                    await transfer_provider.cancel(
                        company_id=state.get("company_id"), intent_id=pending_transfer["intent_id"]
                    )
                except Exception:
                    logger.exception("Failed to cancel an unconfirmable transfer proposal")
                pending_transfer.clear()
                reply = "Bu işlem şu an onay akışı olmadan kullanılamıyor; lütfen chat üzerinden manuel gönderin."

            result = {
                "reply": reply,
                "status": StepStatus.COMPLETED,
                "history": [{"role": "assistant", "content": reply}],
            }
            if flagged:
                result["flagged"] = True
            if referenced_anchor.get("anchor"):
                result["last_referenced_anchor"] = referenced_anchor["anchor"]
            if pending_transfer:
                result["pending_transfer"] = dict(pending_transfer)
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

        Also records a short outcome note into ``history`` for whichever step
        actually ran (see ``_summarize_step_outcome``) -- ``focus`` and
        ``history`` are both "what actually happened this turn" bookkeeping,
        and runs before ``consolidate_memory_node`` specifically so a note
        landing right at the edge of the verbatim window still gets folded
        into the summary the same turn it was produced.
        """
        focus = state.get("focus") or SessionFocus()
        input_text = state.get("input_text", "")
        normalized_input = normalize(input_text)
        reset_requested = any(
            f" {surface} " in f" {normalized_input} " for surface in RESET_SURFACES
        )
        update = compute_focus_update(
            focus,
            document_id=state.get("document_id"),
            plan_intent=state.get("plan_intent"),
            input_text=input_text,
            draft_result=state.get("draft_result") or {},
            assist_result=state.get("assist_result") or {},
            reset_requested=reset_requested,
            brief_answers=(state.get("brief_result") or {}).get("answers"),
        )
        result: dict[str, Any] = {"focus": update} if update else {}
        outcome_note = _summarize_step_outcome(
            state.get("plan_intent"),
            state.get("draft_result") or {},
            state.get("assist_result") or {},
            state.get("classification_result") or {},
        )
        if outcome_note:
            result["history"] = [{"role": "assistant", "content": outcome_note}]
        return result

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
            company_id=state.get("company_id"),
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

    async def _step_brief(
        state: PlanningState, config: RunnableConfig, classification: dict[str, Any], updates: dict[str, Any]
    ) -> None:
        """Resolve the pre-draft writing brief -- deterministic, no interrupt().

        Never pauses the run itself: that happens in brief_gate_node, a
        separate node reached only via route_after_step, for the same
        reason human_gate_node is split from the step that produces
        draft_result -- interrupt() replays its own node from the top on
        resume, and this resolution is cheap enough to replay but the point
        of the split is to keep it that way as the resolver grows.

        Wrapped in its own try/except and degrades to a zero-question
        result (falling back to whatever the session's prior brief already
        carries) on any failure: a bug in a hint-gatherer must never be
        able to leave `brief_result` empty, which would leave `draft`
        looking permanently unready to `step_graph.ready_steps`.

        The prior turn's brief is only carried forward when this turn is a
        `revise` of the still-open `focus.active_draft` -- a fresh `draft`
        request always starts from an empty brief, even mid-session. Without
        this, a second, unrelated "başka birine yazı hazırla" request would
        silently inherit the first draft's muhatap/yazan_taraf/kapanış,
        since `RESET_SURFACES` only covers a handful of explicit
        "yeni bir taslak" phrasings and most fresh-draft requests never say
        one (see intent_rules.RESET_SURFACES's own docstring).
        """
        focus = state.get("focus") or SessionFocus()
        continues_active_draft = (
            state.get("plan_intent") == "revise" and focus.active_draft is not None
        )
        prior_brief = focus.writing_brief if continues_active_draft else None
        try:
            resolution = resolve_brief(state["input_text"], classification, prior_brief)
        except Exception:
            logger.exception("Writing-brief resolution failed; continuing without one.")
            updates["brief_result"] = {
                "status": StepStatus.COMPLETED,
                "answers": dict(prior_brief or {}),
                "resolved": {},
                "questions": [],
            }
            return

        updates["brief_result"] = {
            "status": StepStatus.COMPLETED,
            "answers": {key: item.value for key, item in resolution.resolved.items()},
            # "default"-sourced entries are an optional slot silently
            # defaulted to AUTO_ANSWER (see resolve_brief) -- they were
            # never resolved *from* anything, so showing them in the
            # "Bilinenler" strip as if they were a known fact ("Sen karar
            # ver" appearing as something the system already knows) is
            # backwards. Only genuinely resolved slots are worth surfacing.
            "resolved": {
                key: {"value": item.value, "label": item.label, "source": item.source}
                for key, item in resolution.resolved.items()
                if item.source != "default"
            },
            "questions": list(resolution.questions),
        }

    async def _step_draft(
        state: PlanningState, config: RunnableConfig, classification: dict[str, Any], updates: dict[str, Any]
    ) -> None:
        """Run the draft sub-graph, unless this document isn't what it's about.

        The scope gate (``app.ai.workflows.scope``) already required *some*
        anchor before this plan was even allowed to start -- for a document-
        attached turn, an attached document counts as that anchor on its
        own. This is the narrower check on top: does the request actually
        concern *this* document, now that its classification (in particular
        ``summary``) exists to compare against. Only runs when a document is
        attached; a document-less draft request already had to clear
        ``scope``'s own ``domain_vocabulary`` requirement to get this far, so
        there is nothing further to check it against here.
        """
        document_id = state.get("document_id")
        if document_id:
            verdict = await resolve_relevance(
                state["input_text"], classification, llm_client=intent_client
            )
            if not verdict.relevant:
                logger.info(
                    "Draft refused as unrelated to the attached document: "
                    "reason=%s (%s)",
                    verdict.reason,
                    verdict.detail,
                )
                reason = "İstek yüklü belgeyle ilgili görünmüyor."
                await emit_node_skipped(config, "draft", STEP_LABELS["draft"], reason)
                reply = build_unrelated_reply(
                    classification.get("summary", ""),
                    classification.get("document_type_label", ""),
                )
                updates["assist_result"] = {"reply": reply, "status": StepStatus.COMPLETED}
                updates["draft_result"] = {"status": StepStatus.SKIPPED, "reason": reason}
                updates["history"] = [{"role": "assistant", "content": reply}]
                return

        updates["draft_result"] = await _run_draft(state, classification, config)

    async def _step_routing(
        state: PlanningState, config: RunnableConfig, classification: dict[str, Any], updates: dict[str, Any]
    ) -> None:
        draft_result = updates.get("draft_result") or state.get("draft_result") or {}
        score = draft_result.get("confidence_score", 100.0)
        if draft_result.get("requires_human_approval"):
            score = 0.0
        updates["routing_result"] = await routing_graph.ainvoke(
            {
                "draft": draft_result.get("draft", ""),
                "confidence_score": score,
                # PlanningState.company_id (threaded from ChatService._invoke).
                # Empty only for a state built outside that path (or a stale
                # pre-Faz-4 checkpoint) -- degrades to "no units configured,
                # needs human approval" rather than leaking another company's
                # units into this prompt (see RoutingState.company_id's
                # docstring).
                "company_id": state.get("company_id") or "",
            },
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
        # Faz 4 (#201): the assist step's own propose_transfer tool call
        # produced a pending proposal this turn -- append transfer_execute
        # to plan_steps so the scheduler (step_graph.ready_steps) has
        # something to dispatch once transfer_gate_node confirms it, and
        # record the proposal under the same transfer_resolve_result key
        # the (removed) deterministic path used, so transfer_gate_node/
        # route_after_transfer_gate/_step_transfer_execute/
        # _compile_final_output all keep working unchanged.
        pending_transfer = assist_result.get("pending_transfer")
        if pending_transfer:
            updates["transfer_resolve_result"] = pending_transfer
            updates["plan_steps"] = [*(state.get("plan_steps") or []), "transfer_execute"]

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
            mevzuat_retriever=mevzuat_retriever,
            revise_graph=revise_graph,
            instruction_origin="user_turn",
            company_id=state.get("company_id"),
            today=today_tr(),
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
        options = [
            {"intent": option.get("intent", ""), "label": option.get("label", "")}
            for option in (pending.get("options") or [])
        ]
        # A decision card, not a sentence the user has to answer in prose.
        # The options carry the *same* Turkish labels
        # `_try_resolve_pending_clarification` matches against, so clicking
        # one and typing it out by hand resolve through exactly the same path
        # next turn -- the card is a shortcut, never a second mechanism.
        await emit_question(
            config,
            node="clarify",
            question=question,
            options=[
                {"value": option["intent"], "label": option["label"]}
                for option in options
            ],
            allow_free_text=True,
        )
        updates["assist_result"] = {
            "reply": question,
            "status": StepStatus.COMPLETED,
            "question_options": options,
        }
        # Same reason as _step_revise's marker: the scheduler keys readiness
        # on `clarify_result`, not on the `assist_result` key this step's
        # actual payload lives in.
        updates["clarify_result"] = {"status": StepStatus.COMPLETED}

    async def _step_refuse(
        state: PlanningState, config: RunnableConfig, classification: dict[str, Any], updates: dict[str, Any]
    ) -> None:
        """Answer an out-of-domain request without running anything.

        Deterministic by design (see ``PLAN_BY_INTENT``'s note on the
        ``refuse`` plan): the reply is rendered from
        ``scope.CAPABILITY_MANIFEST``, never generated, so the model that was
        just declined the off-topic request never gets a turn in which to
        fulfil it anyway.
        """
        cached = state.get("cached_document") or {}
        analysis = classification or cached.get("analysis") or {}
        summary = analysis.get("summary", "") if state.get("document_id") else ""
        reply = build_refusal_reply(document_summary=summary)
        updates["assist_result"] = {"reply": reply, "status": StepStatus.COMPLETED}
        updates["refuse_result"] = {"status": StepStatus.COMPLETED}
        updates["history"] = [{"role": "assistant", "content": reply}]

    async def _step_transfer_execute(
        state: PlanningState, config: RunnableConfig, classification: dict[str, Any], updates: dict[str, Any]
    ) -> None:
        """Run the confirmed intent. Only ever reached after
        `route_after_transfer_gate` sees `transfer_resolve_result["outcome"]
        == "confirmed"` -- the real, server-enforced guarantee that nothing
        executes without confirmation lives one layer deeper, in
        `TransferIntentService.execute` itself (it raises unless the
        intent's *persisted* state is `CONFIRMED`, independent of anything
        this graph believes)."""
        resolve_result = state.get("transfer_resolve_result") or {}
        intent_id = resolve_result.get("intent_id")
        company_id = state.get("company_id")
        user_id = state.get("user_id")

        if transfer_provider is None or not intent_id or not company_id or not user_id:
            updates["transfer_execute_result"] = {"status": StepStatus.FAILED, "error": "missing_intent"}
            updates["assist_result"] = {"reply": "Transfer gerçekleştirilemedi.", "status": StepStatus.COMPLETED}
            return

        outcome = await transfer_provider.execute(company_id=company_id, intent_id=intent_id, sender_id=user_id)
        if outcome.error_reason:
            updates["transfer_execute_result"] = {"status": StepStatus.FAILED, "error": outcome.error_reason}
            updates["assist_result"] = {
                "reply": outcome.error_message or "Transfer gerçekleştirilemedi.",
                "status": StepStatus.COMPLETED,
            }
            return

        updates["transfer_execute_result"] = {
            "status": StepStatus.COMPLETED,
            "transfer_id": outcome.id,
            "recipient_id": outcome.recipient_id,
            "artifact_kind": outcome.artifact_kind,
            "snapshot_ref": outcome.snapshot_ref,
            "conversation_id": outcome.conversation_id,
            "cross_unit": outcome.cross_unit,
        }
        noun = "Taslak" if outcome.artifact_kind == "draft" else "Evrak"
        # Template text, not a model generation -- see this module's own
        # docstring on why "gönderdim" must never be something the LLM says.
        updates["assist_result"] = {"reply": f"{noun} gönderildi.", "status": StepStatus.COMPLETED}

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
        "brief": _step_brief,
        "draft": _step_draft,
        "routing": _step_routing,
        "assist": _step_assist,
        "revise": _step_revise,
        "clarify": _step_clarify,
        "refuse": _step_refuse,
        "transfer_execute": _step_transfer_execute,
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
                "tamamlanamadığı için bu adım atlandı."
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
            company_id=state.get("company_id"),
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
            # Reached after the human approval gate's own loop (approve, or
            # gate_revise_node settling without needing another gate round)
            # resolves a plan with no step left to naturally recompute
            # final_output -- "revise" is a single-step plan (see
            # planner.PLAN_BY_INTENT), so nothing downstream of the gate
            # would otherwise ever refresh it, and the turn's reply would
            # silently reflect the stale pre-gate snapshot instead of what
            # the gate actually decided.
            return {"final_output": _compile_final_output(state, {})}

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
        # A transfer-only plan never touches draft_result (it stays `{}`) --
        # transfer_execute_result (or, if the turn ended before execution,
        # transfer_resolve_result) is this plan's own equivalent "did the
        # thing this turn was actually about succeed" signal. Every other
        # plan is unaffected: transfer_result stays `{}` for them, so
        # `status_source` resolves to `draft_result` exactly as before.
        transfer_result = _pick("transfer_execute_result") or _pick("transfer_resolve_result")
        status_source = draft_result if draft_result else transfer_result
        final_status = (
            status_source.get("status")
            if status_source.get("status")
            in {
                StepStatus.FAILED,
                StepStatus.NEEDS_HUMAN_APPROVAL,
                StepStatus.NEEDS_INPUT,
                StepStatus.REVISE_REQUESTED,
                StepStatus.REJECTED,
            }
            else StepStatus.COMPLETED
        )

        output: dict[str, Any] = {
            "status": final_status,
            "plan_steps": list(updates.get("plan_steps") or state.get("plan_steps") or []),
            "intent": updates.get("plan_intent") or state.get("plan_intent") or "",
            "classification": _pick("classification_result"),
            "draft": draft_result,
            "routing": _pick("routing_result"),
            "assist": _pick("assist_result"),
            "transfer": transfer_result,
        }
        if draft_result.get("conflicts") or draft_result.get("changelog"):
            output["revision"] = {
                "conflicts": draft_result.get("conflicts") or [],
                "conflict_notes": draft_result.get("conflict_notes", ""),
                "changelog": draft_result.get("changelog") or {},
                "rounds": state.get("gate_revision_count", 0),
            }
        return output

    async def brief_gate_node(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        """Pause the run for the writing brief's unanswered questions.

        A separate node from `_step_brief` for the same reason `human_gate_node`
        is separate from `execute_step_node`: `interrupt()` replays its own
        node from the top on resume. `_step_brief`'s actual resolution work
        already ran and is sitting in `brief_result` -- resuming here replays
        only a hash and a couple of dict lookups, never `resolve_brief` itself.
        """
        brief_result = state.get("brief_result") or {}
        questions = brief_result.get("questions") or []
        brief_gate_round = state.get("brief_gate_round", 0)

        payload = {
            "kind": "writing_brief",
            "title": "Yazım Briefi",
            "intro": "Taslağı yazmadan önce netleştirmem gereken birkaç nokta var.",
            "questions": questions,
            "resolved": brief_result.get("resolved") or {},
            "round": brief_gate_round,
            "resume_action": "answer",
            "auto_value": AUTO_ANSWER,
        }
        # Deterministic, not a fresh uuid4 -- same reason human_gate_node's
        # hash is: interrupt() re-executes everything before it on resume,
        # including this computation, and it must come out identical both
        # times for the frontend's dedup to work. run_id (not
        # current_step_idx, which brief always runs at index 0 or 1 well
        # before draft) plus brief_gate_round is what gives a re-ask after a
        # blank required answer a distinct id from round 0's.
        interrupt_id = hashlib.sha256(
            f"writing_brief:{'|'.join(sorted(question['key'] for question in questions))}:"
            f"{state.get('run_id', '')}:{brief_gate_round}".encode("utf-8")
        ).hexdigest()[:16]

        HITL_INTERRUPTS.labels(kind="writing_brief").inc()
        await emit_node_start(
            config, "brief_gate", "Yazım Briefi", "Taslak öncesi yazım briefi bekleniyor..."
        )
        await emit_interrupt(
            config, kind="writing_brief", interrupt_id=interrupt_id, payload=payload
        )
        answer = interrupt(payload)
        answer = answer if isinstance(answer, dict) else {}
        await emit_node_end(
            config, "brief_gate", "Yazım Briefi", "Yazım briefi yanıtı alındı.", answer
        )

        if answer.get("action") == "reject":
            reply = "Taslak talebi iptal edildi."
            updates: dict[str, Any] = {
                # Clears `questions` too -- route_after_brief_gate reads it
                # to decide whether to re-pause, and without this the stale
                # pre-reject question list would route straight back to
                # "brief_gate" instead of "end".
                "brief_result": {**brief_result, "questions": []},
                "assist_result": {"reply": reply, "status": StepStatus.COMPLETED},
                "draft_result": {
                    "status": StepStatus.SKIPPED,
                    "reason": "Kullanıcı taslağı iptal etti.",
                },
                "history": [{"role": "assistant", "content": reply}],
            }
            updates["final_output"] = _compile_final_output(state, updates)
            return updates

        raw_answers = answer.get("answers") or {}
        merged_answers = dict(brief_result.get("answers") or {})
        for key, value in raw_answers.items():
            if isinstance(value, list):
                merged_answers[key] = ", ".join(str(item) for item in value if item)
            elif isinstance(value, str):
                merged_answers[key] = value

        required_keys = {
            question["key"] for question in questions if question.get("required", True)
        }
        residual = [key for key in required_keys if not (merged_answers.get(key) or "").strip()]

        if residual:
            residual_questions = [question for question in questions if question["key"] in residual]
            return {
                "brief_result": {
                    **brief_result,
                    "answers": merged_answers,
                    "questions": residual_questions,
                },
                "brief_gate_round": brief_gate_round + 1,
            }

        return {
            "brief_result": {**brief_result, "answers": merged_answers, "questions": []},
            "focus": {"writing_brief": merged_answers},
        }

    def route_after_brief_gate(state: PlanningState) -> str:
        brief_result = state.get("brief_result") or {}
        if brief_result.get("questions"):
            return "brief_gate"
        draft_result = state.get("draft_result") or {}
        if draft_result.get("status") == StepStatus.SKIPPED:
            return "end"
        return "continue"

    async def human_gate_node(
        state: PlanningState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Pause the run for a human answer, then apply it without regenerating.

        A separate node from ``executor`` on purpose: ``interrupt()`` replays
        its own node from the top on resume. Living here, resuming replays a
        few dict lookups; living inside ``execute_step_node`` (which is where
        the draft step itself runs), resuming would replay the entire ~30s
        draft generation the executor already committed to state.

        Only ever reached with a non-empty ``missing_information`` --
        ``route_after_step``/``route_after_gate_revise`` no longer route
        here for a merely low-scoring or guessed-type draft (see their own
        notes). There is deliberately no "İnsan onayı gerekiyor" surface
        anywhere in this system: a draft that is otherwise usable ships
        directly, and the only thing ever asked of the user is which
        specific field is missing.
        """
        draft_result = state.get("draft_result") or {}
        missing_information = draft_result.get("missing_information") or []
        kind = "missing_information"

        # Emit-boundary conversion to the canonical PromptQuestion shape --
        # InfoQuestion stays the internal type everywhere else (apply_answers
        # and the resume contract key off it), this only widens what goes
        # over the wire. Legacy label/why keys are kept alongside the new
        # ones so the pre-existing frontend InfoQuestion[] parsing still
        # works during the transition.
        prompt_questions = [
            {**question, **InfoQuestion(**question).to_prompt_question()}
            for question in missing_information
        ]

        gate_revision_count = state.get("gate_revision_count", 0)
        payload = {
            "kind": kind,
            "questions": prompt_questions,
            "draft": draft_result.get("draft", ""),
            "verification": draft_result.get("verification", {}),
            "judge": draft_result.get("judge", {}),
            "combined_score": draft_result.get("combined_score"),
            "requires_human_approval": draft_result.get("requires_human_approval"),
            "conflicts": draft_result.get("conflicts") or [],
            "conflict_notes": draft_result.get("conflict_notes", ""),
            "changelog": draft_result.get("changelog") or {},
            "revision_round": gate_revision_count,
            "max_revision_rounds": settings.HITL_MAX_GATE_REVISIONS,
            "revision_exhausted": gate_revision_count >= settings.HITL_MAX_GATE_REVISIONS,
        }
        # Deterministic, not a fresh uuid4: interrupt() re-executes everything
        # before it on resume, including this id's computation, and it must
        # come out identical both times for the frontend's dedup to work.
        # gate_revision_count is part of the hash so a second gate round
        # within the same turn gets a distinct id even when the model
        # happens to produce byte-identical text -- without it the
        # frontend's interrupt_id dedup would silently swallow the second
        # round's interrupt and the run would hang waiting for an answer
        # the client thinks it already gave.
        interrupt_id = hashlib.sha256(
            f"{kind}:{draft_result.get('draft', '')}:{state.get('current_step_idx', 0)}:"
            f"{gate_revision_count}".encode("utf-8")
        ).hexdigest()[:16]

        HITL_INTERRUPTS.labels(kind=kind).inc()
        await emit_node_start(
            config,
            "human_gate",
            "Eksik Bilgiler",
            "Eksik alanlar için bilgi bekleniyor...",
        )
        await emit_interrupt(config, kind=kind, interrupt_id=interrupt_id, payload=payload)
        answer = interrupt(payload)
        answer = answer if isinstance(answer, dict) else {}
        # Execution only reaches here after Command(resume=...) -- the gate is
        # now resolved, whatever the human decided.
        await emit_node_end(
            config, "human_gate", "Eksik Bilgiler", "Yanıt alındı, işleme devam ediliyor.", answer
        )

        if kind == "missing_information":
            if answer.get("action") == "revise":
                # Escape hatch: the user typed a revision instruction into
                # what was meant to be an answer box instead of the field's
                # actual value -- apply_answers would otherwise substitute
                # that free text verbatim into the placeholder it was
                # answering, producing a nonsense draft (Görev 2's
                # "revizyon ve bilgi karışıyor" bug). Reuses the same
                # gate_revise machinery route_after_gate already routes a
                # REVISE_REQUESTED status through -- it only inspects
                # draft_result["status"], not kind, so setting the same
                # status here is enough.
                note = (answer.get("instructions") or "").strip()
                return {
                    "gate_revision_note": note,
                    "draft_result": {**draft_result, "status": StepStatus.REVISE_REQUESTED},
                }

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

    async def gate_revise_node(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        """Actually perform the missing-information gate's "revizyon iste"
        escape hatch request.

        A separate node from ``human_gate_node`` for the same reason the
        interrupt lives in its own node at all: resuming replays
        ``human_gate_node`` from the top, and this node's revise sub-graph
        call (a real, possibly multi-second LLM round trip) must not sit
        inside that replay path.

        Builds its own ``DraftVersion`` from ``draft_result`` -- this turn's
        current settled draft -- rather than ``focus.active_draft``:
        ``focus_node`` runs once, at the very end of the turn, so during a
        multi-round gate loop ``focus.active_draft`` is still whatever it
        was at the *start* of this turn. Reading it here would silently
        revise a stale, one-round-older version on every round after the
        first.
        """
        draft_result = state.get("draft_result") or {}
        note = state.get("gate_revision_note", "")

        active_draft = DraftVersion(
            version=0,  # unused -- this DraftVersion is consumed by run_revise, never stored
            text=draft_result.get("draft", ""),
            correspondence_type=draft_result.get("correspondence_type") or "",
            confidence_score=(
                draft_result.get("combined_score") or draft_result.get("confidence_score") or 0.0
            ),
            created_from="draft",
            classification=draft_result.get("classification") or {},
            context=draft_result.get("context") or "",
            source_document=draft_result.get("source_document") or "",
            style_examples=tuple(
                example.get("text", "") if isinstance(example, dict) else str(example)
                for example in (draft_result.get("style_examples") or [])
            ),
            correspondence_type_source=draft_result.get("correspondence_type_source") or "",
            writing_brief=draft_result.get("writing_brief") or {},
        )

        await emit_node_start(
            config, "gate_revise", "Geri Bildirimli Revizyon",
            "Onay kapısındaki geri bildiriminize göre taslak güncelleniyor...",
        )
        result = await run_revise(
            active_draft=active_draft,
            instructions=note,
            correspondence_type=active_draft.correspondence_type,
            llm_client=llm_client,
            fast_llm_client=fast_llm_client,
            reasoning_level=state.get("reasoning_level", ReasoningLevel.BALANCED.value),
            config=config,
            mevzuat_retriever=mevzuat_retriever,
            revise_graph=revise_graph,
            instruction_origin="human_gate",
            company_id=state.get("company_id"),
            today=today_tr(),
        )
        if result.get("status") == StepStatus.FAILED:
            await emit_node_error(
                config, "gate_revise", "Geri Bildirimli Revizyon",
                "Geri bildiriminize göre revizyon üretilemedi.", detail=result.get("error", ""),
            )
        else:
            await emit_node_end(
                config, "gate_revise", "Geri Bildirimli Revizyon",
                "Geri bildiriminize göre taslak güncellendi.", result,
            )

        return {
            "draft_result": result,
            "revise_result": {"status": result.get("status")},
            "gate_revision_count": state.get("gate_revision_count", 0) + 1,
            "gate_revision_note": "",
        }

    async def transfer_gate_node(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        """Pause the transfer flow for its human checkpoint(s).

        Two distinct interrupt kinds share this one node:
        `"needs_disambiguation"` (recipient resolution
        wasn't unique -- ask the human to pick, never the model) and
        `"needs_confirmation"` (the actual send). A disambiguation answer
        that resolves to a single recipient loops back through this same
        node (via `route_after_transfer_gate`) to *also* show the
        confirmation interrupt -- confirmation is never skipped just
        because disambiguation already happened once this turn.
        """
        resolve_result = state.get("transfer_resolve_result") or {}
        outcome = resolve_result.get("outcome")
        intent_id = resolve_result.get("intent_id")
        company_id = state.get("company_id")
        user_id = state.get("user_id")
        gate_round = state.get("transfer_gate_round", 0)

        def _cancelled(reply: str, reason: str) -> dict[str, Any]:
            updates: dict[str, Any] = {
                "assist_result": {"reply": reply, "status": StepStatus.COMPLETED},
                "transfer_execute_result": {"status": StepStatus.SKIPPED, "reason": reason},
            }
            updates["final_output"] = _compile_final_output(state, updates)
            return updates

        if transfer_provider is None or not intent_id or not company_id or not user_id:
            # Not reachable through route_after_step today (it only detours
            # here when the assist step's propose_transfer tool already
            # populated intent_id) -- defensive only.
            return _cancelled("Transfer işlemi bulunamadı.", "missing_intent")

        if outcome == "needs_disambiguation":
            candidates = resolve_result.get("candidate_recipients") or []
            payload = {
                "kind": "artifact_transfer_disambiguate",
                "candidates": candidates,
                "artifact_kind": resolve_result.get("artifact_kind"),
                "round": gate_round,
            }
            interrupt_id = hashlib.sha256(
                f"artifact_transfer_disambiguate:{intent_id}:{gate_round}".encode("utf-8")
            ).hexdigest()[:16]
            HITL_INTERRUPTS.labels(kind="artifact_transfer_disambiguate").inc()
            await emit_node_start(
                config, "transfer_gate", "Alıcı Seçimi", "Alıcı seçiminiz bekleniyor..."
            )
            await emit_interrupt(
                config, kind="artifact_transfer_disambiguate", interrupt_id=interrupt_id, payload=payload
            )
            answer = interrupt(payload)
            answer = answer if isinstance(answer, dict) else {}
            await emit_node_end(
                config, "transfer_gate", "Alıcı Seçimi", "Alıcı seçimi alındı.", answer
            )

            # `recipient_id` travels either as a top-level resume field or
            # nested in `answers` (the shape `/chat/resume`'s
            # `ChatResumeRequest.answers` -- shared with every other
            # interrupt kind -- actually carries it in). Accepting both
            # keeps this node usable from a direct `Command(resume=...)`
            # call (tests) without requiring a second resume contract.
            recipient_id = answer.get("recipient_id") or (answer.get("answers") or {}).get("recipient_id")
            if answer.get("action") != "select" or not recipient_id:
                await transfer_provider.cancel(company_id=company_id, intent_id=intent_id)
                return _cancelled("Transfer işlemi iptal edildi.", "cancelled")

            intent = await transfer_provider.select_recipient(
                company_id=company_id,
                intent_id=intent_id,
                recipient_id=recipient_id,
                requester_id=user_id,
            )
            if intent.error_reason:
                return _cancelled(intent.error_message or "Bu seçim artık geçerli değil.", intent.error_reason)
            if intent.state == "POLICY_DENIED":
                message = (
                    (intent.policy_snapshot or {}).get("message_tr")
                    or "Bu transfer şu anda gerçekleştirilemiyor."
                )
                return _cancelled(message, "policy_denied")

            # Now AWAITING_CONFIRMATION -- loop back into this same node
            # (route_after_transfer_gate) for the confirmation interrupt.
            return {
                "transfer_resolve_result": {
                    **resolve_result,
                    "outcome": "needs_confirmation",
                    "cross_unit": intent.cross_unit,
                    "policy_snapshot": intent.policy_snapshot,
                },
                "transfer_gate_round": gate_round + 1,
            }

        # needs_confirmation
        payload = {
            "kind": "artifact_transfer_confirm",
            "artifact_kind": resolve_result.get("artifact_kind"),
            "source_artifact_id": resolve_result.get("source_artifact_id"),
            "source_version": resolve_result.get("source_version"),
            "cross_unit": bool(resolve_result.get("cross_unit")),
            "round": gate_round,
        }
        interrupt_id = hashlib.sha256(
            f"artifact_transfer_confirm:{intent_id}:{gate_round}".encode("utf-8")
        ).hexdigest()[:16]
        HITL_INTERRUPTS.labels(kind="artifact_transfer_confirm").inc()
        await emit_node_start(
            config, "transfer_gate", "Transfer Onayı", "Transfer onayınız bekleniyor..."
        )
        await emit_interrupt(
            config, kind="artifact_transfer_confirm", interrupt_id=interrupt_id, payload=payload
        )
        answer = interrupt(payload)
        answer = answer if isinstance(answer, dict) else {}
        await emit_node_end(
            config, "transfer_gate", "Transfer Onayı", "Transfer onayı alındı.", answer
        )

        if answer.get("action") != "approve":
            await transfer_provider.cancel(company_id=company_id, intent_id=intent_id)
            return _cancelled("Transfer işlemi iptal edildi.", "cancelled")

        intent = await transfer_provider.confirm(company_id=company_id, intent_id=intent_id, requester_id=user_id)
        if intent.error_reason:
            return _cancelled(intent.error_message or "Bu onay artık geçerli değil.", intent.error_reason)

        # CONFIRMED -- route_after_transfer_gate sends this to the executor
        # for transfer_execute; TransferIntentService.execute is the actual
        # enforcement point (it refuses anything not CONFIRMED, independent
        # of what this graph believes -- see _step_transfer_execute).
        return {
            "transfer_resolve_result": {**resolve_result, "outcome": "confirmed"},
        }

    def route_after_transfer_gate(state: PlanningState) -> str:
        if state.get("transfer_execute_result"):
            # _cancelled already set final_output too.
            return "end"
        outcome = (state.get("transfer_resolve_result") or {}).get("outcome")
        if outcome == "confirmed":
            return "continue"
        return "transfer_gate"

    def route_after_step(state: PlanningState) -> str:
        steps = state.get("plan_steps") or []

        if (
            has_checkpointer
            and settings.HITL_BRIEF_GATE_ENABLED
            and state.get("_last_ran_step") == "brief"
            and (state.get("brief_result") or {}).get("questions")
        ):
            return "brief_gate"

        # Detours to the confirmation gate whenever the assist step's own
        # propose_transfer tool call just produced a pending proposal this
        # turn -- checked by outcome/settlement, not by `_last_ran_step`,
        # since "assist" (unlike "transfer_resolve" in the now-removed
        # deterministic path) is a step that runs for plenty of turns that
        # never touch transfer at all.
        if has_checkpointer and state.get("_last_ran_step") == "assist":
            outcome = (state.get("transfer_resolve_result") or {}).get("outcome")
            if outcome in {"needs_disambiguation", "needs_confirmation"} and not state.get(
                "transfer_execute_result"
            ):
                return "transfer_gate"

        if has_checkpointer and state.get("_last_ran_step") in {"draft", "revise"}:
            draft_result = state.get("draft_result") or {}
            draft_status = draft_result.get("status")
            # NEEDS_HUMAN_APPROVAL (a low verifier score, a guessed
            # correspondence type, ...) deliberately does NOT pause the run
            # here -- only a genuinely unfilled `[...]` field does (see
            # human_gate_node's own docstring). The score/flag itself is
            # still recorded on draft_result for scoring/audit; it just no
            # longer blocks delivery on a human clicking "approve".
            if draft_status == StepStatus.NEEDS_INPUT:
                return "human_gate"

        return "end" if all_steps_settled(steps, state) else "continue"

    def route_after_gate(state: PlanningState) -> str:
        draft_result = state.get("draft_result") or {}
        status = draft_result.get("status")
        if status == StepStatus.NEEDS_INPUT:
            return "human_gate"
        if status == StepStatus.REJECTED:
            return "end"
        if status == StepStatus.REVISE_REQUESTED:
            # Bounded: once the round cap is hit, the gate stops offering
            # another automatic revision and the turn ends with whatever
            # text the last successful round produced (see
            # SessionFocus._VERSIONABLE_DRAFT_STATUSES's own docstring on
            # why that is still safe to version).
            if state.get("gate_revision_count", 0) < settings.HITL_MAX_GATE_REVISIONS:
                return "gate_revise"
            return "end"
        return "continue"

    def route_after_gate_revise(state: PlanningState) -> str:
        draft_result = state.get("draft_result") or {}
        status = draft_result.get("status")
        if status == StepStatus.FAILED:
            return "end"
        if not has_checkpointer:
            return "continue"
        if status == StepStatus.NEEDS_INPUT:
            return "human_gate"
        # NEEDS_HUMAN_APPROVAL never re-opens the gate here either -- see
        # route_after_step's identical note. A conflict finding was never
        # grounds for the gate on its own either: app.ai.revision.conflict's
        # audit_node already reports it as a non-blocking chat notice
        # (applied_anyway is a hard invariant: the instruction was applied
        # in full regardless).
        return "continue"

    builder = StateGraph(PlanningState)
    builder.add_node("planning", planning_node)
    builder.add_node("executor", execute_step_node)
    builder.add_node("brief_gate", brief_gate_node)
    builder.add_node("human_gate", human_gate_node)
    builder.add_node("gate_revise", gate_revise_node)
    builder.add_node("transfer_gate", transfer_gate_node)
    builder.add_node("focus", focus_node)
    builder.add_node("consolidate_memory", consolidate_memory_node)

    builder.add_edge(START, "planning")
    builder.add_edge("planning", "executor")
    builder.add_conditional_edges(
        "executor",
        route_after_step,
        {
            "continue": "executor",
            "brief_gate": "brief_gate",
            "human_gate": "human_gate",
            "transfer_gate": "transfer_gate",
            "end": "focus",
        },
    )
    builder.add_conditional_edges(
        "brief_gate",
        route_after_brief_gate,
        {"brief_gate": "brief_gate", "continue": "executor", "end": "focus"},
    )
    builder.add_conditional_edges(
        "human_gate",
        route_after_gate,
        {
            "human_gate": "human_gate",
            "gate_revise": "gate_revise",
            "continue": "executor",
            "end": "focus",
        },
    )
    builder.add_conditional_edges(
        "gate_revise",
        route_after_gate_revise,
        {"human_gate": "human_gate", "continue": "executor", "end": "focus"},
    )
    builder.add_conditional_edges(
        "transfer_gate",
        route_after_transfer_gate,
        {"transfer_gate": "transfer_gate", "continue": "executor", "end": "focus"},
    )
    builder.add_edge("focus", "consolidate_memory")
    builder.add_edge("consolidate_memory", END)

    return builder.compile(checkpointer=checkpointer)
