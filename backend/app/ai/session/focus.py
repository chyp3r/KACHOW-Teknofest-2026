"""Session-scoped state that survives across turns.

``PlanningState``'s other fields are turn-scoped -- ``planning_node`` resets
every ``*_result`` key at the start of each turn (see
``app.ai.workflows.planning_graph``). ``SessionFocus`` is the deliberate
exception: a LangGraph channel that is never reset, carrying whatever a task
needs to survive from one message to the next -- which draft is "the" draft
right now, what the user is trying to accomplish across a multi-turn
negotiation, and (once later phases add the flows that consume them) an
open clarification question and the document location the user last
referred to.

Without this, a system built entirely from turn-scoped state has no concept
of "what are we working on" -- every message is answered as if it were the
first, which is exactly why a conversational revision ("3. paragrafı daha
resmi yap") had nowhere to attach to before this existed.
"""

import dataclasses
from typing import Any, Literal, Optional

#: draft_result statuses that represent a real, user-visible draft text --
#: worth recording as a version. Deliberately excludes REVISE_REQUESTED,
#: REJECTED and FAILED: a revise request has no new text yet (the actual
#: revision flow that would produce one doesn't exist until a later phase),
#: a rejection and a failure aren't versions of anything.
_VERSIONABLE_DRAFT_STATUSES = frozenset(
    {"COMPLETED", "NEEDS_HUMAN_APPROVAL", "NEEDS_INPUT", "APPROVED"}
)

#: Intents whose message is worth folding into the session's objective.
#: A greeting or a document question isn't part of "what the user wants
#: built"; a draft/analyze/revise request is.
_OBJECTIVE_INTENTS = frozenset({"draft", "analyze", "revise"})

#: `objective`'s upper bound. A handful of short turns' worth -- enough for
#: "taslak hazırla" + "kime" + "Valiliğe'ye" to all still be present, not so
#: much that a long session's objective grows without bound.
OBJECTIVE_CHAR_CAP = 500


@dataclasses.dataclass(frozen=True)
class DraftVersion:
    """One settled state of the active draft.

    Attributes:
        version: 1-based, increases by one each time a new version replaces
            the previous one. Never reused.
        text: The draft text at this version.
        correspondence_type: The resolved correspondence type it was
            written under.
        confidence_score: The verifier's combined score at this version.
        created_from: How this version came to exist.
        classification: The document analysis this version was grounded in.
            Carried forward so a later `revise` turn can rebuild the same
            grounding brief without re-running classification -- revise
            never re-classifies (see `app.ai.workflows.revise`).
        context: The verified legislation excerpts this version was grounded
            in, for the same reason.
        source_document: The incoming document text this version responds
            to, for the same reason -- without it, a revise turn's
            groundedness check has strictly less material to match claims
            against than the original draft's did.
    """

    version: int
    text: str
    correspondence_type: str
    confidence_score: float
    created_from: Literal["draft", "revise", "human_fill"]
    classification: dict[str, Any] = dataclasses.field(default_factory=dict)
    context: str = ""
    source_document: str = ""


@dataclasses.dataclass(frozen=True)
class SessionFocus:
    """Task-level state that persists across turns on the same thread.

    Attributes:
        active_document_id: Storage path of the document the session is
            currently working with.
        active_draft: The draft version currently open for revision or
            approval, or ``None`` while there is no in-progress draft.
        draft_history: Every settled version, oldest first (``active_draft``
            is always ``draft_history[-1]`` when set).
        objective: A short, accumulated statement of what the user is
            trying to accomplish across a multi-turn negotiation. Bounded
            (see ``OBJECTIVE_CHAR_CAP``) rather than an unbounded log.
        pending_clarification: Set when the system asked a clarifying
            question and is waiting on the answer. Reserved for the
            ``clarify`` flow; unused until it exists.
        last_referenced_anchor: The document location a deictic reference
            ("bu madde", "burası") should resolve to. Reserved for document
            addressing; unused until it exists.
        last_intent: The most recently resolved intent. ``PlanningState``'s
            own ``plan_intent`` channel already carries this turn-to-turn
            (nothing resets it), but it lives among fields that mean
            "this turn's result" -- this is the same value read from the
            place that means "the session's state", for a future consumer
            that shouldn't have to know the distinction.
    """

    active_document_id: Optional[str] = None
    active_draft: Optional[DraftVersion] = None
    draft_history: tuple[DraftVersion, ...] = ()
    objective: str = ""
    pending_clarification: Optional[dict[str, Any]] = None
    last_referenced_anchor: Optional[str] = None
    last_intent: Optional[str] = None


def _accumulate_objective(existing: str, addition: str) -> str:
    """Append a new fragment to ``existing``, dropping the oldest overflow.

    Args:
        existing: The session's current objective text.
        addition: The new turn's contribution.

    Returns:
        The combined objective, capped to ``OBJECTIVE_CHAR_CAP`` characters
        by dropping from the front -- the newest fragment is always kept
        whole rather than being the one cut off mid-sentence.
    """
    addition = addition.strip()
    if not addition:
        return existing
    combined = f"{existing} | {addition}" if existing else addition
    if len(combined) <= OBJECTIVE_CHAR_CAP:
        return combined
    return combined[-OBJECTIVE_CHAR_CAP:]


def compute_focus_update(
    focus: SessionFocus,
    *,
    document_id: Optional[str],
    plan_intent: Optional[str],
    input_text: str,
    draft_result: dict[str, Any],
) -> dict[str, Any]:
    """Derive this turn's partial ``SessionFocus`` update.

    Pure function -- the graph node wrapping this only reads ``state`` and
    passes it a dict, so the actual decision of what changes is unit
    testable without a compiled graph.

    Args:
        focus: The session's focus as of the start of this turn.
        document_id: This turn's attached document, if any.
        plan_intent: The intent resolved for this turn.
        input_text: The user's message this turn.
        draft_result: This turn's settled ``draft_result``, if the plan
            included a draft step. Empty when it didn't.

    Returns:
        A partial update for the ``focus`` channel (see ``merge_focus``).
        Empty when nothing changed.
    """
    update: dict[str, Any] = {}

    if document_id:
        update["active_document_id"] = document_id

    if plan_intent:
        update["last_intent"] = plan_intent
        if plan_intent in _OBJECTIVE_INTENTS:
            update["objective"] = _accumulate_objective(focus.objective, input_text)

    draft_status = (draft_result or {}).get("status")
    if draft_status in _VERSIONABLE_DRAFT_STATUSES:
        # Keyed off which step actually produced this turn's result, not
        # inferred from "a draft already existed" -- the latter mislabeled
        # any second, entirely unrelated draft request in a later turn as a
        # "revise" of the first.
        created_from = "revise" if plan_intent == "revise" else "draft"
        version = DraftVersion(
            version=len(focus.draft_history) + 1,
            text=draft_result.get("draft", ""),
            correspondence_type=draft_result.get("correspondence_type") or "",
            confidence_score=(
                draft_result.get("combined_score")
                or draft_result.get("confidence_score")
                or 0.0
            ),
            created_from=created_from,
            classification=draft_result.get("classification") or {},
            context=draft_result.get("context") or "",
            source_document=draft_result.get("source_document") or "",
        )
        update["active_draft"] = version
        update["draft_history"] = (*focus.draft_history, version)

    return update


def merge_focus(
    left: Optional[SessionFocus], right: Optional[dict[str, Any]]
) -> SessionFocus:
    """LangGraph reducer: apply a partial update onto the session's focus.

    Args:
        left: The channel's existing value.
        right: A partial update, e.g. ``{"active_draft": ...}`` -- a node
            returns only the fields it changed, the same convention every
            other ``PlanningState`` update already follows.

    Returns:
        The merged ``SessionFocus``.
    """
    base = left or SessionFocus()
    if not right:
        return base
    return dataclasses.replace(base, **right)
