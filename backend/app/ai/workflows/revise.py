"""The revise flow's public entry point: ``run_revise``.

A thin façade over ``app.ai.workflows.revise_graph``'s compiled LangGraph
workflow -- parsing (``app.ai.revision.instruction``), conditional
re-retrieval, targeted rewrite, verify/repair loop and conflict audit all
live there now (see that module's docstring for the full topology). This
module exists so every existing caller and test that imports
``parse_revision_instruction``, ``locate_target``, ``_merge`` or
``run_revise`` from ``app.ai.workflows.revise`` keeps working unchanged.
"""

import logging
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from app.ai.adapters.company_adapter import AdapterProvider
from app.ai.adapters.company_rules import RulesProvider
from app.ai.identity.company_profile import ProfileProvider
from app.ai.llms.base import BaseLLMClient
from app.ai.reasoning_levels import get_reasoning_level_preset
from app.ai.revision.instruction import (
    EditDirective,
    Operation,
    RevisionInstruction,
    Scope,
    TargetSpan,
    _merge,
    decompose_instruction,
    locate_target,
    needs_reretrieval,
    parse_revision_instruction,
)
from app.ai.session.focus import DraftVersion
from app.ai.workflows.events import child_config
from app.ai.workflows.revise_graph import create_revise_graph
from app.core.enums.step_status import StepStatus

logger = logging.getLogger(__name__)

#: Re-exported for callers (and tests) that imported these from this module
#: before parsing moved to app.ai.revision.instruction, and before the flow
#: itself moved to a compiled sub-graph.
__all__ = [
    "EditDirective",
    "Operation",
    "RevisionInstruction",
    "Scope",
    "TargetSpan",
    "decompose_instruction",
    "locate_target",
    "needs_reretrieval",
    "parse_revision_instruction",
    "run_revise",
]


async def run_revise(
    *,
    active_draft: DraftVersion,
    instructions: str,
    correspondence_type: str,
    llm_client: BaseLLMClient,
    fast_llm_client: Optional[BaseLLMClient],
    reasoning_level: str,
    config: Optional[RunnableConfig] = None,
    emit_token_fn=None,
    mevzuat_retriever: Optional[Any] = None,
    revise_graph: Optional[Any] = None,
    instruction_origin: str = "user_turn",
    company_id: Optional[str] = None,
    adapter_provider: Optional[AdapterProvider] = None,
    rules_provider: Optional[RulesProvider] = None,
    profile_provider: Optional[ProfileProvider] = None,
    today: str = "",
) -> dict[str, Any]:
    """Produce a targeted revision of the active draft.

    Returns a dict shaped like ``draft_graph``'s own output (``status``,
    ``draft``, ``correspondence_type``, ``confidence_score``,
    ``combined_score``, ``verification``, ``judge``, ``missing_information``,
    ``requires_human_approval``, ``classification``, ``context``,
    ``source_document``) so downstream code -- ``human_gate_node``,
    ``_step_routing``, and ``focus_node``'s versioning -- treats a revised
    draft uniformly with a freshly generated one. Additionally carries
    ``conflicts``, ``conflict_notes``, ``changelog``, ``pii_findings``,
    ``repair_items``, ``attempt_history``, ``retrieval_meta`` and
    ``instruction_origin``, all new in the sub-graph version of this flow.

    Args:
        active_draft: The draft version being revised, carrying its own
            grounding (``classification``/``context``/``source_document``/
            ``style_examples``/``correspondence_type_source``) forward from
            when it was written.
        instructions: The user's revise request, unparsed.
        correspondence_type: Falls back to ``active_draft``'s own type when
            the caller has nothing more specific (there is nothing to
            re-resolve here -- revise never re-classifies).
        llm_client: Quality-tier client.
        fast_llm_client: Fast-tier client, used for the optional judge and
            the conflict auditor. Falls back to ``llm_client`` when omitted,
            same as draft_graph.
        reasoning_level: Selects the judge's on/off default the same way
            draft_graph's reflexion loop does.
        config: Runnable config, forwarded into the sub-graph so its nodes'
            own ``emit_token``/``emit_node_*`` calls reach the SSE queue
            (see ``app.ai.workflows.events.child_config``).
        emit_token_fn: Unused -- kept only so existing callers that still
            pass ``emit_token_fn=emit_token`` do not need to change. Token
            streaming now happens inside the sub-graph itself via ``config``.
        mevzuat_retriever: Optional retriever for conditional legislation
            re-retrieval (see ``app.ai.revision.retrieval``).
        revise_graph: A pre-compiled graph to invoke instead of building one
            from ``llm_client``/``fast_llm_client``/``mevzuat_retriever`` --
            lets a caller building many revisions (or a test) compile once.
        instruction_origin: ``"user_turn"`` for an ordinary revise turn,
            ``"human_gate"`` when this call is answering the approval gate's
            own "revizyon iste" action (see ``planning_graph.gate_revise_node``).
            Carried straight through into the result so
            ``SessionFocus.compute_focus_update`` can tell them apart.
        company_id: Which tenant this revision is for -- resolves this
            company's runtime style adapter (Faz C2). None skips adapter
            resolution entirely, same as omitting ``adapter_provider``.
        adapter_provider: Async callable resolving a company's adapter (see
            ``app.domains.companies.provider.get_company_adapter``),
            forwarded to ``create_revise_graph`` when this call builds its
            own graph. Ignored when ``revise_graph`` is supplied pre-built
            -- that graph's own adapter_provider (or lack of one) already
            applies.
        rules_provider: Async callable resolving a company's mandatory
            drafting rules (see
            ``app.domains.companies.provider.get_company_rules``),
            forwarded to ``create_revise_graph`` the same way
            ``adapter_provider`` is (C27) -- without this, a caller that
            builds its own graph through this fallback (rather than
            passing a pre-built ``revise_graph``, the way every caller in
            this codebase today happens to) silently lost the company's
            mandatory rules on every revision, even though the original
            draft enforced them. Ignored when ``revise_graph`` is supplied
            pre-built -- that graph's own rules_provider already applies.
        profile_provider: Async callable resolving a company's identity
            profile (see
            ``app.domains.companies.provider.get_company_profile``),
            forwarded the same way (Faz 6). Ignored when ``revise_graph``
            is supplied pre-built.
        today: The date this revision is happening on (see
            app.ai.workflows.dates.today_tr), forwarded so
            revise_graph.verify_node's own date-placeholder backstop can
            fill a "Tarih:" placeholder if the rewrite pass reintroduces
            one -- an ordinary revision keeps the original draft's date
            unchanged (see revise_graph's own anti-date-change rule) and
            never needs this, but a rewrite that legitimately regenerates
            the header still must not turn into a question to the user.

    Returns:
        The revision result.
    """
    del emit_token_fn  # unused; see docstring

    preset = get_reasoning_level_preset(reasoning_level)
    resolved_correspondence_type = correspondence_type or active_draft.correspondence_type
    graph = revise_graph or create_revise_graph(
        llm_client, fast_llm_client, mevzuat_retriever, adapter_provider, rules_provider,
        profile_provider,
    )

    try:
        final_state = await graph.ainvoke(
            {
                "active_draft": active_draft,
                "instructions": instructions,
                "reasoning_level": preset.level.value,
                "company_id": company_id or "",
                "today": today,
            },
            config=child_config(config),
        )
    except Exception as exc:
        logger.exception("Revise sub-graph invocation failed")
        return {
            "draft": active_draft.text,
            "correspondence_type": resolved_correspondence_type,
            "correspondence_sub_genre": active_draft.correspondence_sub_genre,
            "confidence_score": 0.0,
            "combined_score": 0.0,
            "requires_human_approval": True,
            "status": StepStatus.FAILED,
            "error": f"Revizyon üretilemedi: {exc}",
            "classification": active_draft.classification,
            "context": active_draft.context,
            "source_document": active_draft.source_document,
            "writing_brief": active_draft.writing_brief,
        }

    status = final_state.get("status", StepStatus.FAILED)
    if status == StepStatus.FAILED:
        return {
            "draft": final_state.get("draft", active_draft.text),
            "correspondence_type": resolved_correspondence_type,
            "correspondence_sub_genre": active_draft.correspondence_sub_genre,
            "confidence_score": 0.0,
            "combined_score": 0.0,
            "requires_human_approval": True,
            "status": StepStatus.FAILED,
            "error": final_state.get("error", "Revizyon üretilemedi."),
            "classification": active_draft.classification,
            "context": active_draft.context,
            "source_document": active_draft.source_document,
            "writing_brief": active_draft.writing_brief,
        }

    return {
        "draft": final_state.get("draft", active_draft.text),
        "correspondence_type": final_state.get("correspondence_type") or resolved_correspondence_type,
        "confidence_score": final_state.get("confidence_score", 0.0),
        "combined_score": final_state.get("combined_score", 0.0),
        "requires_human_approval": final_state.get("requires_human_approval", True),
        "evaluation_notes": final_state.get("evaluation_notes", ""),
        "verification": final_state.get("verification", {}),
        "judge": final_state.get("judge", {}),
        "judge_available": final_state.get("judge_available", False),
        "repair_items": final_state.get("repair_items", []),
        "pii_findings": final_state.get("pii_findings", []),
        "missing_information": final_state.get("missing_information", []),
        "attempt_history": final_state.get("attempt_history", []),
        # C29: these two used to fall out of the sub-graph result here --
        # revise_graph.verify_node computes and returns both (the same
        # auditable rule breakdown and attempt count draft_graph's own
        # result carries), but this façade never surfaced them, so every
        # revised draft persisted with an empty applied_rules and no
        # attempt count regardless of what the sub-graph actually did.
        "applied_rules": final_state.get("applied_rules", []),
        "attempts": final_state.get("attempts", 0),
        "conflicts": final_state.get("conflicts", []),
        "conflict_notes": final_state.get("conflict_notes", ""),
        "changelog": final_state.get("changelog", {}),
        "retrieval_meta": final_state.get("retrieval_meta", {}),
        "status": status,
        "classification": active_draft.classification,
        "context": final_state.get("context") or active_draft.context,
        "source_document": active_draft.source_document,
        # Carried forward unchanged from the version being revised, not
        # re-derived -- a revision neither retrieves new style examples nor
        # re-resolves the correspondence type (see this module's docstring).
        # Needed so a *second* gate_revise round (see
        # planning_graph.gate_revise_node) building its own DraftVersion
        # from this dict still has them, instead of silently losing the
        # PII/fallback-type gate parity and leak detection revise_graph's
        # verify_node depends on.
        "style_examples": [{"text": text} for text in active_draft.style_examples],
        "correspondence_type_source": active_draft.correspondence_type_source,
        "correspondence_sub_genre": final_state.get("correspondence_sub_genre")
        or active_draft.correspondence_sub_genre,
        "writing_brief": active_draft.writing_brief,
        "reasoning_level": preset.level.value,
        "instruction_origin": instruction_origin,
    }
