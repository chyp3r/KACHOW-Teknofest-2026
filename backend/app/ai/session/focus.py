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
#: worth recording as a version. FAILED is excluded: it carries no new text.
#: REVISE_REQUESTED is included -- unintuitively, since it sounds like "no
#: text yet" -- because the only way it reaches this function as a *turn's
#: final* status is the human approval gate's revision-round cap being hit
#: (see planning_graph.route_after_gate/gate_revise_node): by construction,
#: every "revizyon iste" click that still has rounds left is immediately
#: superseded by a real gate_revise_node result before the turn can end, so
#: a REVISE_REQUESTED status reaching here always carries the *last actually
#: produced* revision's text, just capped from trying one more round -- not
#: a request with nothing behind it yet.
_VERSIONABLE_DRAFT_STATUSES = frozenset(
    {"COMPLETED", "NEEDS_HUMAN_APPROVAL", "NEEDS_INPUT", "APPROVED", "REVISE_REQUESTED"}
)

#: draft_result statuses that end the active draft's life without producing
#: a new version of it -- the existing version is annotated and archived
#: instead (see compute_focus_update's rejection branch). REJECTED is the
#: only one: unlike REVISE_REQUESTED above, a rejection is a real decision
#: about the *existing* text, not new text of its own.
_ARCHIVE_ONLY_DRAFT_STATUSES = frozenset({"REJECTED"})

#: Intents whose message is worth folding into the session's objective.
#: A greeting or a document question isn't part of "what the user wants
#: built"; a draft/analyze/revise request is.
_OBJECTIVE_INTENTS = frozenset({"draft", "analyze", "revise"})

#: Intents that count as the user actively working on the open draft, as
#: opposed to merely coexisting with one. Distinct from `_OBJECTIVE_INTENTS`
#: above: `analyze` folds into the session's stated objective just as much as
#: `draft`/`revise` do, but inspecting some other document is not evidence
#: the active draft is still what the user is doing right now.
_DRAFT_TOUCHING_INTENTS = frozenset({"draft", "revise"})

#: `objective`'s upper bound. A handful of short turns' worth -- enough for
#: "taslak hazırla" + "kime" + "Valiliğe'ye" to all still be present, not so
#: much that a long session's objective grows without bound.
OBJECTIVE_CHAR_CAP = 500

#: Turns an active draft may sit untouched by a draft/revise turn before it
#: is treated as abandoned. Without this, `active_draft` -- once set --
#: never clears itself (nothing else in this module writes `None` to it),
#: so `has_active_draft` stays permanently true for the rest of the thread
#: and every `REVISE_RULES` surface keeps firing long after the
#: conversation moved on to something unrelated.
ACTIVE_DRAFT_IDLE_LIMIT = 10


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
        style_examples: The few-shot style-example texts this version was
            written with (see ``retrieve_examples_node``), carried forward
            so a later `revise` turn's verifier can run the same
            ``ornek_sizintisi`` leak check the original draft got --
            without this a revision's verify pass had strictly weaker
            grounding checks than the draft it revised.
        correspondence_type_source: Whether ``correspondence_type`` was
            resolved from an explicit signal or guessed (``"fallback"``,
            see ``resolve_correspondence_type``). Carried forward so a
            revise turn's approval gate applies the same "a guessed type
            needs a human" rule ``draft_graph.verify_node`` always has.
        correspondence_sub_genre: A free-text genre label ("itiraz
            dilekçesi") when this version targets a specific genre outside
            the four spec'd CorrespondenceType values -- empty for a core
            type. Carried forward so a later `revise` turn keeps writing in
            the same genre instead of drifting back to generic
            "diğer resmî yazışma" phrasing (see ``resolve_correspondence_type``).
        status: The ``draft_result`` status this version was recorded
            under (e.g. ``"COMPLETED"``, ``"NEEDS_HUMAN_APPROVAL"``,
            ``"REJECTED"``). Informational -- nothing here re-derives
            behaviour from it, it is for a caller (a history view, a log)
            that wants to show what happened without re-deriving it from
            ``created_from``/``rejection_reason``.
        rejection_reason: Why this version was rejected, when
            ``created_from == "rejected"``. Empty otherwise.
        conflicts: This version's own instruction-vs-mevzuat/source
            conflict findings, when it was produced by a revision (see
            ``app.ai.revision.conflict``). Empty for a fresh draft.
        changelog: This version's own change log against the version it
            replaced, when it was produced by a revision (see
            ``app.ai.revision.changelog``). Empty for a fresh draft.
    """

    version: int
    text: str
    correspondence_type: str
    confidence_score: float
    created_from: Literal["draft", "revise", "human_fill", "gate_revise", "rejected"]
    classification: dict[str, Any] = dataclasses.field(default_factory=dict)
    context: str = ""
    source_document: str = ""
    style_examples: tuple[str, ...] = ()
    correspondence_type_source: str = ""
    correspondence_sub_genre: str = ""
    #: The pre-draft writing brief this version was written under (see
    #: app.ai.workflows.writing_brief) -- who's writing, who it's going to,
    #: anlatım/kapanış. Carried forward for the same reason
    #: classification/context/source_document are: a later `revise` turn
    #: rebuilds the same grounding brief without re-resolving it, and must
    #: not drift back to an unstated direction the way the original
    #: "KACMAK ekibi olarak" bug did.
    writing_brief: dict[str, Any] = dataclasses.field(default_factory=dict)
    status: str = ""
    rejection_reason: str = ""
    conflicts: tuple[dict[str, Any], ...] = ()
    changelog: dict[str, Any] = dataclasses.field(default_factory=dict)


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
        active_draft_idle_turns: Turns since ``active_draft`` was last
            produced or worked on (see ``_DRAFT_TOUCHING_INTENTS``). Reset to
            0 whenever the user is actively drafting or revising; once it
            reaches ``ACTIVE_DRAFT_IDLE_LIMIT``, ``active_draft`` clears
            itself. Meaningless while ``active_draft`` is ``None``.
        last_rejection: The most recently rejected version's own summary
            (``{"version", "reason", "draft"}``), set whenever a
            ``REJECTED`` draft_result archives the active draft (see
            ``compute_focus_update``). Lets a reply or a later turn
            reference "the draft you just rejected" without walking
            ``draft_history`` to find it.
        writing_brief: Answers from the pre-draft writing-brief gate (see
            ``app.ai.workflows.writing_brief``), carried across turns so a
            second draft/revise turn in the same session doesn't re-ask who
            is writing to whom. Cleared whenever ``active_draft`` is reset
            (see ``compute_focus_update``'s ``reset_requested`` branch) --
            otherwise "yeni bir taslak yazalım" would silently inherit the
            previous letter's addressee.
    """

    active_document_id: Optional[str] = None
    active_draft: Optional[DraftVersion] = None
    draft_history: tuple[DraftVersion, ...] = ()
    objective: str = ""
    pending_clarification: Optional[dict[str, Any]] = None
    last_referenced_anchor: Optional[str] = None
    last_intent: Optional[str] = None
    active_draft_idle_turns: int = 0
    last_rejection: Optional[dict[str, Any]] = None
    writing_brief: Optional[dict[str, Any]] = None


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


def _draft_version_from_result(
    draft_result: dict[str, Any],
    *,
    version: int,
    created_from: Literal["draft", "revise", "human_fill", "gate_revise", "rejected"],
    rejection_reason: str = "",
) -> DraftVersion:
    """Build a ``DraftVersion`` straight from a settled ``draft_result``.

    Shared by the ordinary versioning branch and the "rejected with no
    prior active_draft" branch of ``compute_focus_update`` -- both start
    from the same raw material, they only differ in ``created_from`` and
    (for a rejection) the reason.
    """
    return DraftVersion(
        version=version,
        text=draft_result.get("draft", ""),
        correspondence_type=draft_result.get("correspondence_type") or "",
        confidence_score=(
            draft_result.get("combined_score") or draft_result.get("confidence_score") or 0.0
        ),
        created_from=created_from,
        classification=draft_result.get("classification") or {},
        context=draft_result.get("context") or "",
        source_document=draft_result.get("source_document") or "",
        style_examples=tuple(
            example.get("text", "") if isinstance(example, dict) else str(example)
            for example in (draft_result.get("style_examples") or [])
        ),
        correspondence_type_source=draft_result.get("correspondence_type_source") or "",
        correspondence_sub_genre=draft_result.get("correspondence_sub_genre") or "",
        writing_brief=draft_result.get("writing_brief") or {},
        status=str(draft_result.get("status") or ""),
        conflicts=tuple(draft_result.get("conflicts") or ()),
        changelog=draft_result.get("changelog") or {},
        rejection_reason=rejection_reason,
    )


def compute_focus_update(
    focus: SessionFocus,
    *,
    document_id: Optional[str],
    plan_intent: Optional[str],
    input_text: str,
    draft_result: dict[str, Any],
    assist_result: Optional[dict[str, Any]] = None,
    reset_requested: bool = False,
    brief_answers: Optional[dict[str, Any]] = None,
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
        assist_result: This turn's settled ``assist_result``, if the plan
            included an assist step. Carries ``last_referenced_anchor`` when
            a document tool read a specific page this turn (see
            ``app.ai.tools.document_tools``).
        reset_requested: Whether this turn's message explicitly asked to
            abandon the open draft (see ``app.ai.workflows.intent_rules.
            RESET_SURFACES``). Takes effect only when this turn didn't also
            produce a new version -- an explicit reset and a settled draft
            in the same turn cannot both be true of a real message, and a
            freshly produced version winning that contradiction is the safer
            of the two readings.
        brief_answers: This turn's settled ``brief_result["answers"]``, if
            the plan included a ``brief`` step. Carried forward
            unconditionally so a turn whose brief resolved silently (no
            gate needed) still persists it for the next turn -- the gate
            itself already writes the same value directly when it does
            fire (see ``planning_graph.brief_gate_node``); this is what
            covers the no-gate path. Overridden by an explicit
            ``reset_requested`` below, which always wins.

    Returns:
        A partial update for the ``focus`` channel (see ``merge_focus``).
        Empty when nothing changed.
    """
    update: dict[str, Any] = {}

    if brief_answers:
        update["writing_brief"] = brief_answers

    anchor = (assist_result or {}).get("last_referenced_anchor")
    if anchor:
        update["last_referenced_anchor"] = anchor

    if document_id:
        update["active_document_id"] = document_id

    if plan_intent:
        update["last_intent"] = plan_intent
        if plan_intent in _OBJECTIVE_INTENTS:
            update["objective"] = _accumulate_objective(focus.objective, input_text)

    draft_status = (draft_result or {}).get("status")
    produced_version = draft_status in _VERSIONABLE_DRAFT_STATUSES
    # A rejection reachable with no prior `focus.active_draft` is not an edge
    # case -- it is the *ordinary* first-approval reject: a turn that both
    # drafts and gets rejected within the same turn (gate interrupts before
    # focus_node ever runs, see focus_node's own docstring) never had a
    # chance to become `focus.active_draft` first. `draft_result["draft"]`
    # is what carries the real text either way.
    archived_rejection = draft_status in _ARCHIVE_ONLY_DRAFT_STATUSES and bool(
        focus.active_draft is not None or draft_result.get("draft")
    )
    if produced_version:
        # Keyed off which step actually produced this turn's result, not
        # inferred from "a draft already existed" -- the latter mislabeled
        # any second, entirely unrelated draft request in a later turn as a
        # "revise" of the first. A result from the human approval gate's own
        # "revizyon iste" loop (see planning_graph.gate_revise_node) is
        # distinguished from an ordinary revise turn -- both are still a
        # revision, but one happened inside the gate, not the plan.
        if draft_result.get("instruction_origin") == "human_gate":
            created_from = "gate_revise"
        elif plan_intent == "revise":
            created_from = "revise"
        else:
            created_from = "draft"
        version = _draft_version_from_result(
            draft_result, version=len(focus.draft_history) + 1, created_from=created_from,
        )
        update["active_draft"] = version
        update["draft_history"] = (*focus.draft_history, version)
    elif archived_rejection:
        # A rejection is a decision about the *existing* text, not new text
        # of its own. When that text was already `focus.active_draft` (a
        # draft rejected in a later turn than the one that produced it), it
        # is annotated in place -- replacing its own entry in
        # `draft_history`, which the SessionFocus invariant guarantees is
        # that same object -- rather than appended as a second,
        # textually-identical version. Otherwise (rejected within the same
        # turn it was drafted, before ever reaching `focus.active_draft`) a
        # fresh version is built straight from `draft_result`, tagged
        # rejected from the start. Either way the draft is archived, never
        # lost -- see this module's docstring for why that matters.
        reason = (draft_result.get("rejection_reason") or "").strip()
        if focus.active_draft is not None:
            rejected_version = dataclasses.replace(
                focus.active_draft, created_from="rejected", status=str(draft_status),
                rejection_reason=reason,
            )
            if focus.draft_history and focus.draft_history[-1] is focus.active_draft:
                history = (*focus.draft_history[:-1], rejected_version)
            else:
                history = (*focus.draft_history, rejected_version)
        else:
            rejected_version = _draft_version_from_result(
                draft_result, version=len(focus.draft_history) + 1, created_from="rejected",
                rejection_reason=reason,
            )
            history = (*focus.draft_history, rejected_version)
        update["draft_history"] = history
        update["active_draft"] = None
        update["last_rejection"] = {
            "version": rejected_version.version, "reason": reason, "draft": rejected_version.text,
        }

    # The active draft's lifetime: touching it (producing a version, or a
    # draft/revise turn even when that particular attempt didn't settle one --
    # e.g. it needs more input) keeps its idle clock at zero; an explicit
    # reset phrase or ACTIVE_DRAFT_IDLE_LIMIT turns of anything else clears
    # it. `draft_history` is untouched either way -- this only decides which
    # version, if any, counts as "the" open one right now.
    if produced_version or archived_rejection:
        update["active_draft_idle_turns"] = 0
    elif reset_requested and focus.active_draft is not None:
        update["active_draft"] = None
        update["active_draft_idle_turns"] = 0
        update["writing_brief"] = None
    elif focus.active_draft is not None:
        if plan_intent in _DRAFT_TOUCHING_INTENTS:
            update["active_draft_idle_turns"] = 0
        else:
            idle_turns = focus.active_draft_idle_turns + 1
            if idle_turns >= ACTIVE_DRAFT_IDLE_LIMIT:
                update["active_draft"] = None
                update["active_draft_idle_turns"] = 0
            else:
                update["active_draft_idle_turns"] = idle_turns

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
