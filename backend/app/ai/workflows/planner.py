"""Intent resolution for the master workflow.

The choice between the system's four flows used to be a full structured LLM call
against an orchestrator prompt, which cost a round trip plus a Pydantic retry
loop on the critical path. That was replaced by an ordered keyword cascade:
check draft phrases, then analyze phrases, then greetings, and return on the
first hit.

The cascade removed the model call but made the *order* the decision, and that
is not fixable by reordering. Measured on ``evaluation/datasets/intents.jsonl``
it scored 0.00 on two whole categories:

* ``inversion`` -- with draft checked first, "Resmi yazı ne demek?" matched
  "resmi yazi" and started a three-step drafting pipeline. Reordering only moves
  the failure: with analyze first, "analiz sonrası taslak hazırla" resolves to
  analysis.
* ``precedence`` -- the greeting branch was gated on ``document_id is None``, so
  "Merhaba" with a document attached fell past every branch and escalated to the
  model, and "İyi akşamlar, yarın devam ederiz" after a draft turn matched the
  continuation rule on "devam" and produced a draft.

This module now scores a message against a declarative evidence table
(:mod:`app.ai.workflows.intent_rules`) and decides on the **margin** between the
top two intents rather than on which rule fired first. Evidence accumulates
instead of short-circuiting, so a contested message stays visibly contested --
which is what lets it resolve to a compound plan or escalate, instead of being
resolved by table order. Still no model call, still sub-millisecond.

Only genuinely balanced or evidence-free messages fall through to a model, and
that call remains a single label from the fast tier.
"""

import logging
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, Optional

from pydantic import BaseModel, Field

from app.ai.llms.base import BaseLLMClient
from app.ai.session.focus import SessionFocus
from app.ai.workflows.intent_rules import CONTINUATION_SURFACES, Intent
from app.ai.workflows.intent_scorer import (
    COMPOUND_FLOOR,
    DECISIVE_MARGIN,
    PRESENCE_FLOOR,
    IntentScores,
    normalize,
    score_intents,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance only
    from app.ai.semantic.prototype_matcher import PrototypeMatcher

logger = logging.getLogger(__name__)

__all__ = [
    "Intent",
    "IntentOutput",
    "PLAN_BY_INTENT",
    "PlanDecision",
    "classify_intent_with_model",
    "normalize",
    "resolve_plan",
    "resolve_plan_deterministic",
]

#: Step sequences per intent.
#:
#: Note the absence of a separate ``rag`` step in the draft flow. The
#: classification sub-graph already retrieves legislation for the document and
#: puts it in ``mevzuat_documents``; running the RAG graph afterwards repeated
#: the same retrieval behind an extra query-rewrite LLM call and threw the first
#: result away.
#:
#: ``chat`` and ``document_qa`` used to be two separate plans here. They are
#: now one: ``assist`` is a single tool-using agent that answers conversationally
#: and reaches for document retrieval itself when the question needs it, rather
#: than the router having to decide in advance whether an answer needs the
#: document. See ``app.ai.workflows.planning_graph``'s ``_run_assist``.
#: ``revise`` is deliberately its own single-step plan, not a variant of
#: ``draft``: it never re-runs classification and never re-retrieves
#: legislation, only the one LLM call that rewrites the targeted part of the
#: already-active draft (see ``app.ai.workflows.revise``). ``clarify`` costs
#: nothing at all -- it renders a question from ``PlanDecision.clarification``
#: and ends the turn there.
PLAN_BY_INTENT: dict[str, list[str]] = {
    "draft": ["classification", "draft", "routing"],
    "analyze": ["classification"],
    "assist": ["assist"],
    "revise": ["revise"],
    "clarify": ["clarify"],
}

REASONING_BY_INTENT: dict[str, str] = {
    "draft": "Resmî yazı talebi tespit edildi: evrak analizi, taslak üretimi ve birim yönlendirmesi çalıştırılacak.",
    "analyze": "Evrak analizi talebi tespit edildi: sınıflandırma ve uygunluk denetimi çalıştırılacak.",
    "assist": "Genel bir soru veya belge hakkında bir soru tespit edildi: asistan yanıtı hazırlanacak.",
    "revise": "Mevcut taslakta bir revizyon talebi tespit edildi: hedefli düzeltme çalıştırılacak.",
    "clarify": "İstek belirsiz olduğu için kullanıcıya açıklayıcı bir soru soruldu.",
}

#: Canonical execution order, used to merge two intents' step lists without
#: letting the merge invent an ordering of its own. ``clarify`` is absent on
#: purpose: it never appears in a compound plan (see ``COMPOUND_PAIR``).
STEP_ORDER: tuple[str, ...] = (
    "classification",
    "draft",
    "revise",
    "routing",
    "assist",
)

#: Intents expensive enough that a wrong guess costs real LLM calls and
#: wall-clock time (a full draft run, or a targeted rewrite) rather than a
#: single conversational reply -- see ``resolve_plan``'s clarify-vs-guess
#: decision.
_EXPENSIVE_INTENTS = frozenset({"draft", "revise"})

#: Turkish description of each intent, used to phrase a clarifying question
#: in terms a user recognizes rather than an internal name like "revise".
_CLARIFY_LABELS: dict[str, str] = {
    "draft": "bir taslak hazırlama isteği",
    "revise": "mevcut taslakta bir revizyon isteği",
    "analyze": "bir evrak analizi isteği",
    "assist": "genel bir soru veya sohbet",
}

#: A bare confirmation to a clarifying question selects its leading option --
#: the same short-affirmative vocabulary the continuation rule already uses
#: for confirming a *decisive* turn, reused here for confirming an
#: *undecided* one.
_AFFIRMATIVE_SURFACES = CONTINUATION_SURFACES

#: The only pair worth running as one plan. ``draft`` already begins with
#: ``classification``, so "incele ve cevap yaz" is a single pipeline rather than
#: two. Every other contested pair is a genuine ambiguity and escalates instead
#: -- merging ``assist`` into ``draft`` would answer conversationally *and*
#: start a drafting run, which is not what either reading of the message asked
#: for.
COMPOUND_PAIR = frozenset({"draft", "analyze"})


class PlanDecision(NamedTuple):
    """The resolved execution plan for one user message.

    Attributes:
        steps: The sub-workflows to run, in order.
        intent: The resolved intent.
        reasoning: Turkish rationale shown to the user.
        source: Which mechanism decided. ``scored`` for a decisive margin,
            ``compound`` for a merged plan, ``continuation``/``empty`` for the
            two special cases, ``model``/``context_default`` when the
            deterministic layer abstained.
        confidence: The decision's own confidence in [0, 1], derived from the
            margin. Lets a caller threshold on it rather than treating every
            deterministic answer as equally certain.
        evidence: Ids of the rules that fired. Recorded so a production
            decision can be explained after the fact -- the previous resolver
            reported only which branch it took, never which phrase matched.
        alternatives: Runner-up intents with their scores, highest first.
        clarification: Set only when ``intent == "clarify"``: the question
            and its options (``[{"intent", "label"}, ...]``), written into
            ``SessionFocus.pending_clarification`` so the next turn's reply
            can be resolved against the same options instead of re-scoring
            from nothing (see ``_try_resolve_pending_clarification``).
    """

    steps: list[str]
    intent: Intent
    reasoning: str
    source: str
    confidence: float = 1.0
    evidence: tuple[str, ...] = ()
    alternatives: tuple[tuple[str, float], ...] = ()
    clarification: Optional[dict[str, Any]] = None


class IntentOutput(BaseModel):
    """Single-label intent classification, used only for ambiguous messages."""

    intent: Literal["draft", "analyze", "assist"] = Field(
        description=(
            "Kullanıcının niyeti. draft: resmi yazı/taslak hazırlanması isteniyor. "
            "analyze: evrakın analiz edilmesi isteniyor. "
            "assist: genel sohbet veya yüklü bir belge hakkında soru soruluyor."
        )
    )


def _merge_steps(intents: frozenset[str]) -> list[str]:
    """Union two intents' step lists, keeping canonical execution order.

    Args:
        intents: The intents to merge.

    Returns:
        The merged step list.
    """
    merged = {step for intent in intents for step in PLAN_BY_INTENT[intent]}
    return [step for step in STEP_ORDER if step in merged]


def _decision(
    intent: str, scores: IntentScores, source: str, reasoning_suffix: str = ""
) -> PlanDecision:
    """Build a decision for a single resolved intent."""
    return PlanDecision(
        steps=list(PLAN_BY_INTENT[intent]),
        intent=intent,  # type: ignore[arg-type]
        reasoning=REASONING_BY_INTENT[intent] + reasoning_suffix,
        source=source,
        confidence=round(scores.confidence, 3),
        evidence=tuple(scores.evidence),
        alternatives=tuple(scores.ranked[1:3]),
    )


def resolve_plan_deterministic(
    message: str,
    document_id: Optional[str],
    previous_intent: Optional[str] = None,
    has_active_draft: bool = False,
) -> Optional[PlanDecision]:
    """Resolve the plan without a model, when the evidence allows it.

    Args:
        message: The user's message.
        document_id: Storage path of an attached document, when present.
        previous_intent: The intent resolved for this thread's previous turn,
            when known. Lets a short affirmative ("evet, hazırla") continue a
            draft/analyze/revise offer instead of being read as conversational
            filler.
        has_active_draft: Whether ``SessionFocus.active_draft`` is set --
            gates ``revise``'s rules (see ``score_intents``).

    Returns:
        A decision, or None when the evidence is too weak or too evenly split
        to commit -- which is the signal to escalate, not a failure.
    """
    scores = score_intents(message, document_id, previous_intent, has_active_draft)
    return _decide_from_scores(scores)


def _decide_from_scores(scores: IntentScores) -> Optional[PlanDecision]:
    """The deterministic decision, given scores already computed once.

    Split out of :func:`resolve_plan_deterministic` so :func:`resolve_plan`
    can reuse the same ``IntentScores`` for both the deterministic attempt and
    the contested-candidate fallback below, instead of scoring the message
    twice for one turn.
    """
    ranked = scores.ranked

    if not ranked:
        logger.info("Intent abstained: no rule fired.")
        return None

    top_intent, top_score = ranked[0]

    # Nothing scored highly enough to be a candidate at all. Without this floor
    # a lone weak hint would read as a confident decision purely because
    # nothing contested it.
    if top_score < PRESENCE_FLOOR:
        logger.info("Intent abstained: top score %.2f below presence floor.", top_score)
        return None

    # Compound is checked before the margin, not after it. "Uygunluk denetimi
    # yap, sonra cevabı kaleme al" carries explicit evidence for both readings
    # but scores them unevenly, so a margin test would resolve it to analysis
    # alone and silently drop the drafting half of the request. When both
    # intents are independently well-attested, the message asked for both --
    # how lopsided the scores happen to be is not the question.
    present = {
        intent: score for intent, score in ranked if score >= COMPOUND_FLOOR
    }
    if COMPOUND_PAIR.issubset(present):
        return PlanDecision(
            steps=_merge_steps(COMPOUND_PAIR),
            intent="draft",
            reasoning=(
                REASONING_BY_INTENT["draft"]
                + " (hem inceleme hem taslak istendiği tespit edildi)"
            ),
            source="compound",
            confidence=round(scores.confidence, 3),
            evidence=tuple(scores.evidence),
            alternatives=tuple(scores.ranked[1:3]),
        )

    if scores.margin >= DECISIVE_MARGIN:
        if "assist.empty_message" in scores.evidence:
            return _decision(top_intent, scores, "empty")
        if f"{top_intent}.continuation" in scores.evidence:
            return _decision(
                top_intent, scores, "continuation", " (önceki isteğin devamı)"
            )
        return _decision(top_intent, scores, "scored")

    # Two readings, evenly matched, and not the one pair that composes. This is
    # the honest escalation case: the evidence really is balanced, so guessing
    # would be worse than paying for a single fast-tier label.
    runner_up_intent, runner_up_score = ranked[1]
    logger.info(
        "Intent abstained: %s (%.2f) vs %s (%.2f), margin %.2f.",
        top_intent,
        top_score,
        runner_up_intent,
        runner_up_score,
        scores.margin,
    )
    return None


def _build_clarify_decision(scores: IntentScores) -> PlanDecision:
    """Build a deterministic, LLM-free clarifying question from contested scores.

    Called when neither the lexical nor the semantic rung was decisive and
    the leading (non-decisive) candidate is expensive enough that guessing
    wrong is worse than asking -- see ``resolve_plan``.

    Args:
        scores: The scoring outcome that was too close to call.

    Returns:
        A ``clarify`` decision carrying the question and its options in
        ``clarification``.
    """
    top_two = list(scores.ranked[:2])
    if len(top_two) == 1:
        # Only one candidate ever cleared the presence floor, but nothing
        # contested it decisively enough either -- pair it with `assist` so
        # the question still offers a real alternative, not a confirmation
        # of a foregone conclusion.
        top_two.append(("assist", 0.0))

    options = [
        {"intent": intent, "label": _CLARIFY_LABELS.get(intent, intent)}
        for intent, _ in top_two
    ]
    question = (
        f"Bu isteğinizi {options[0]['label']} olarak mı, yoksa "
        f"{options[1]['label']} olarak mı değerlendirmemi istersiniz?"
    )

    return PlanDecision(
        steps=list(PLAN_BY_INTENT["clarify"]),
        intent="clarify",
        reasoning=REASONING_BY_INTENT["clarify"],
        source="clarify",
        confidence=round(scores.confidence, 3),
        evidence=tuple(scores.evidence),
        alternatives=tuple(top_two),
        clarification={"question": question, "options": options},
    )


def _try_resolve_pending_clarification(
    message: str, pending: Optional[dict[str, Any]]
) -> Optional[PlanDecision]:
    """Resolve a reply against an open clarifying question, if it answers it.

    Checked before the normal ladder runs at all: an explicit answer to
    "taslak mı, revizyon mu?" must not be re-scored from nothing, where a
    short reply could easily fall below the presence floor on its own.

    Args:
        message: The user's new message.
        pending: ``SessionFocus.pending_clarification``, or ``None``/empty
            when there is nothing open.

    Returns:
        A decision for whichever option the reply selected, or ``None`` when
        the message doesn't clearly answer the question -- the caller then
        falls through to the normal ladder, and the stale clarification is
        superseded rather than forced onto an unrelated new message.
    """
    if not pending:
        return None
    options = pending.get("options") or []
    if not options:
        return None

    normalized = normalize(message)
    words = normalized.split()

    selected: Optional[str] = None
    if len(words) <= 4 and any(
        f" {surface} " in f" {normalized} " for surface in _AFFIRMATIVE_SURFACES
    ):
        selected = options[0]["intent"]
    else:
        for option in options:
            label = option.get("label") or ""
            candidate_intent = option.get("intent") or ""
            if (label and normalize(label) in normalized) or (
                candidate_intent and normalize(candidate_intent) in normalized
            ):
                selected = candidate_intent
                break

    if not selected or selected not in PLAN_BY_INTENT:
        return None

    return PlanDecision(
        steps=list(PLAN_BY_INTENT[selected]),
        intent=selected,  # type: ignore[arg-type]
        reasoning=REASONING_BY_INTENT[selected]
        + " (açıklayıcı soruya verilen yanıtla çözüldü)",
        source="clarification_resolved",
        confidence=1.0,
        evidence=("clarification.resolved",),
    )


async def classify_intent_with_model(
    llm_client: BaseLLMClient, message: str, document_id: Optional[str]
) -> Intent:
    """Fall back to a one-label model call for genuinely ambiguous messages.

    Args:
        llm_client: Fast-tier LLM client.
        message: The user's message.
        document_id: Storage path of an attached document, when present.

    Returns:
        The classified intent, defaulting to a safe value on failure.
    """
    from app.ai.agents.base import BaseAgent

    agent = BaseAgent(
        llm_client=llm_client,
        name="IntentClassifier",
        description="Classifies a user message into one of three workflow intents.",
        system_prompt=(
            "Kullanıcı mesajını üç niyetten birine ata. Yalnızca yapılandırılmış "
            "JSON döndür, açıklama yazma.\n"
            "- draft: resmî yazı, cevap yazısı, üst yazı veya taslak hazırlanması isteniyor.\n"
            "- analyze: bir evrakın analiz edilmesi, sınıflandırılması veya eksiklerinin "
            "bulunması isteniyor.\n"
            "- assist: yukarıdakilerin hiçbiri; genel sohbet, sistem hakkında soru veya "
            "yüklü bir belgenin içeriği hakkında soru."
        ),
    )

    prompt = (
        f'Mesaj: "{message}"\n'
        f"Sisteme yüklü bir belge var mı: {'evet' if document_id else 'hayır'}\n\n"
        "Bu mesajın niyetini belirle."
    )

    try:
        result: IntentOutput = await agent.run_structured(
            messages=prompt,
            response_model=IntentOutput,
            temperature=0.0,
            max_retries=1,
        )
        return result.intent
    except Exception:
        logger.warning("Intent classification failed; falling back by context.")
        # Safe default: the cheapest flow that can still answer, whether or not
        # a document is attached -- assist reaches for retrieval itself when it
        # needs to. Never the full three-step drafting pipeline, which is what
        # the old fallback chose and which turned every planner hiccup into the
        # slowest possible response.
        return "assist"


async def resolve_plan(
    message: str,
    document_id: Optional[str],
    llm_client: Optional[BaseLLMClient] = None,
    previous_intent: Optional[str] = None,
    matcher: Optional["PrototypeMatcher"] = None,
    focus: Optional[SessionFocus] = None,
) -> PlanDecision:
    """Resolve the execution plan for a user message.

    Cheapest first. The lexical layer answers almost everything at no cost;
    the semantic layer separates a real paraphrase from a genuinely unclear
    message at roughly a twentieth of what a model call costs. What's left
    once both abstain no longer escalates to the model by default: a cheap
    candidate (``assist``) is guessed, an expensive one (``draft``/``revise``)
    is asked about instead of risked, and the model rung is now reserved for
    the case neither rung produced any signal for at all.

    Args:
        message: The user's message.
        document_id: Storage path of an attached document, when present.
        llm_client: Fast-tier client for the genuinely signal-free case. When
            omitted, that case resolves by context instead of by model.
        previous_intent: The intent resolved for this thread's previous turn,
            when known -- enables the short-affirmative continuation rule.
        matcher: Prototype matcher for the semantic rung. Omitted or unavailable
            means the ladder simply skips it, exactly as before it existed.
        focus: The session's persistent focus. Supplies whether a draft is
            active (gates ``revise``) and any open clarifying question
            (checked first, before the ladder runs at all).

    Returns:
        The execution plan and the rationale shown to the user.
    """
    if focus is not None and focus.pending_clarification:
        resolved = _try_resolve_pending_clarification(
            message, focus.pending_clarification
        )
        if resolved is not None:
            logger.info(
                "Plan resolved via pending clarification: intent=%s", resolved.intent
            )
            return resolved

    has_active_draft = bool(focus and focus.active_draft is not None)

    scores = score_intents(message, document_id, previous_intent, has_active_draft)
    decided = _decide_from_scores(scores)
    if decided is not None:
        logger.info(
            "Plan resolved deterministically (%s): %s", decided.source, decided.steps
        )
        return decided

    if matcher is not None:
        match = await matcher.match(message, "intent")
        if match is not None and match.decisive and match.label in PLAN_BY_INTENT:
            logger.info(
                "Plan resolved semantically: intent=%s similarity=%.3f gap=%.3f",
                match.label,
                match.similarity,
                match.runner_up_gap,
            )
            return PlanDecision(
                steps=list(PLAN_BY_INTENT[match.label]),
                intent=match.label,  # type: ignore[arg-type]
                reasoning=REASONING_BY_INTENT[match.label],
                source="semantic",
                confidence=round(match.similarity, 3),
                evidence=(f"semantic.{match.label}",),
            )
        if match is not None:
            logger.info(
                "Semantic match not decisive (%s, similarity=%.3f, gap=%.3f); "
                "checking whether it's worth a clarifying question before the model.",
                match.label,
                match.similarity,
                match.runner_up_gap,
            )

    # Neither rung was decisive. Reuses the scores computed above rather than
    # asking `score_intents` to redo the same arithmetic for the same message.
    candidate = scores.ranked[0][0] if scores.ranked else None

    if candidate is None:
        if llm_client is None:
            intent: Intent = "assist"
            source = "context_default"
        else:
            intent = await classify_intent_with_model(llm_client, message, document_id)
            source = "model"
        logger.info("Plan resolved via %s: intent=%s", source, intent)
        return PlanDecision(
            list(PLAN_BY_INTENT[intent]), intent, REASONING_BY_INTENT[intent], source
        )

    if candidate in _EXPENSIVE_INTENTS:
        logger.info(
            "Contested candidate '%s' is expensive to guess wrong; asking instead.",
            candidate,
        )
        return _build_clarify_decision(scores)

    logger.info("Contested candidate '%s' is cheap; guessing rather than asking.", candidate)
    return _decision(candidate, scores, "guessed_cheap")
