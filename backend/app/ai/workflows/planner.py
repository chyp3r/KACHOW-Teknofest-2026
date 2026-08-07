"""Intent resolution for the master workflow.

The choice between the system's flows used to be a full structured LLM call
against an orchestrator prompt, then an ordered keyword cascade, then a
three-rung ladder (lexical score -> semantic prototype -> fast-tier model)
where whichever rung answered first decided alone and the others were never
consulted. The ladder fixed the cascade's "table order is the decision"
failure, but introduced its own: the lexical layer's margin test gated
*everything*, including messages an unambiguous imperative should have
settled outright. "Cevap yaz." scores `draft=3.0` (an explicit request) against
`assist=2.0` (the generic "short message with no document" structural hint) --
a margin of 1.0, just under the old ladder's 1.2 threshold -- and fell through
to a clarifying question a user should never have been asked. The margin test
cannot tell an explicit imperative apart from a weak structural hint once both
are already folded into the same per-intent sum; reordering the rungs does not
fix that, the same way reordering the cascade never fixed *its* failure.

This module now keeps every signal source distinct (see
:mod:`app.ai.workflows.router_features`) and combines them through a
calibrated linear model (:mod:`app.ai.workflows.router_fusion`, coefficients
in :mod:`app.ai.policy.router_weights`, fit offline by
``scripts/fit_router.py``) instead of letting one rung's own internal test
gate the others. The result is one probability per intent, and the decision
policy is a simple band on the winner's probability:

* At or above ``tau_high`` -- committed outright (``source="fused"``).
* Between ``tau_low`` and ``tau_high`` -- genuinely contested; a fast-tier
  model call breaks the tie when one is available (``source="model"``).
* Below ``tau_low`` -- too little signal to be worth a model call either;
  asks the user (``source="clarify"``).

Two things do not go through fusion at all, on purpose:

* A **compound** request (both ``draft`` and ``analyze`` independently
  well-attested) is checked on the raw additive lexical scores *before*
  fusion runs. A softmax's classes compete for probability mass by
  construction, so it cannot represent "both readings are independently
  strong" -- see ``scripts/fit_router.py``'s module docstring for why
  training even excludes these cases rather than trying to teach it to.
* An **open clarifying question's answer** is resolved against the pending
  question's own options, before the message is scored at all -- an
  affirmative like "evet, hazırla" would otherwise be re-scored from
  (almost) nothing.
"""

import logging
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, Optional

from pydantic import BaseModel, Field

from app.ai.llms.base import BaseLLMClient
from app.ai.policy import get_policy
from app.ai.policy.router_weights import ROUTER_WEIGHTS
from app.ai.session.focus import SessionFocus
from app.ai.workflows.intent_rules import CONTINUATION_SURFACES, Intent
from app.ai.workflows.intent_scorer import COMPOUND_FLOOR, IntentScores, normalize, score_intents
from app.ai.workflows.router_features import RouterSignals, extract_features
from app.ai.workflows.router_fusion import predict_proba

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
]

#: Step sequences per intent.
#:
#: Note the absence of a separate ``rag`` step in the draft flow. The
#: classification sub-graph already retrieves legislation for the document and
#: puts it in ``mevzuat_documents``; running the RAG graph afterwards repeated
#: the same retrieval behind an extra query-rewrite LLM call and threw the first
#: result away.
#:
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
        source: Which mechanism decided. ``compound`` for a merged plan (see
            ``COMPOUND_PAIR``), ``clarification_resolved`` when a pending
            question's answer settled it, ``fused`` when the calibrated
            fusion probability cleared ``tau_high`` on its own,
            ``model``/``model_failed`` when it needed the fast-tier model to
            break a tie, ``clarify`` when even that wasn't warranted or
            available.
        confidence: The decision's own confidence in [0, 1]. For ``fused`` and
            ``clarify`` this is the fusion layer's own calibrated probability
            for the winning/leading intent -- directly comparable across
            every source now, unlike the three incompatible scales
            (lexical margin, raw cosine similarity, a hardcoded 1.0) the
            pre-fusion ladder reported under the same field.
        evidence: Ids of the lexical rules that fired, when any did. Recorded
            so a production decision can be explained after the fact.
        alternatives: Runner-up intents with their fused probabilities,
            highest first.
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
    """Single-label intent classification, used only for genuinely contested messages."""

    intent: Literal["draft", "analyze", "assist"] = Field(
        description=(
            "Kullanıcının niyeti. draft: resmi yazı/taslak hazırlanması isteniyor. "
            "analyze: evrakın analiz edilmesi isteniyor. "
            "assist: yukarıdakilerin hiçbiri; genel sohbet veya yüklü bir belge hakkında soru."
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


def _try_compound(lexical: IntentScores) -> Optional[PlanDecision]:
    """Detect a compound draft+analyze request from the raw lexical scores.

    Checked before fusion runs at all -- see the module docstring for why a
    softmax cannot represent this case the way an additive score can.

    Args:
        lexical: The message's lexical evidence, already scored.

    Returns:
        A merged ``draft``+``analyze`` plan, or None when the message isn't
        independently well-attested for both.
    """
    present = {intent: score for intent, score in lexical.ranked if score >= COMPOUND_FLOOR}
    if not COMPOUND_PAIR.issubset(present):
        return None

    return PlanDecision(
        steps=_merge_steps(COMPOUND_PAIR),
        intent="draft",
        reasoning=(
            REASONING_BY_INTENT["draft"] + " (hem inceleme hem taslak istendiği tespit edildi)"
        ),
        source="compound",
        confidence=round(lexical.confidence, 3),
        evidence=tuple(lexical.evidence),
        alternatives=tuple(lexical.ranked[1:3]),
    )


def _fused_decision(
    intent: str,
    probs: dict[str, float],
    ranked: list[tuple[str, float]],
    lexical: IntentScores,
    source: str,
) -> PlanDecision:
    """Build a decision for an intent the fusion probability committed to."""
    return PlanDecision(
        steps=list(PLAN_BY_INTENT[intent]),
        intent=intent,  # type: ignore[arg-type]
        reasoning=REASONING_BY_INTENT[intent],
        source=source,
        confidence=round(probs[intent], 3),
        evidence=tuple(lexical.evidence),
        alternatives=tuple(ranked[1:3]),
    )


def _build_clarify_decision(ranked: list[tuple[str, float]]) -> PlanDecision:
    """Build a clarifying question from the fused probabilities.

    Called when the fused distribution is too flat to commit to (below
    ``tau_low``) or was contested and no model was available to break the
    tie (see ``resolve_plan``). Unlike the pre-fusion ladder's version of
    this function, there is no "only one candidate exists" special case to
    handle: softmax always produces a full distribution over all four
    intents, so a runner-up is always available to offer as the question's
    second option.

    Args:
        ranked: Intents sorted by fused probability, highest first.

    Returns:
        A ``clarify`` decision carrying the question and its options in
        ``clarification``.
    """
    top_two = ranked[:2]
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
        confidence=round(top_two[0][1], 3),
        evidence=(),
        alternatives=tuple(top_two),
        clarification={"question": question, "options": options},
    )


def _try_resolve_pending_clarification(
    message: str, pending: Optional[dict[str, Any]]
) -> Optional[PlanDecision]:
    """Resolve a reply against an open clarifying question, if it answers it.

    Checked before the fusion decision runs at all: an explicit answer to
    "taslak mı, revizyon mu?" must not be re-scored from nothing, where a
    short reply could easily read as low-signal on its own.

    Args:
        message: The user's new message.
        pending: ``SessionFocus.pending_clarification``, or ``None``/empty
            when there is nothing open.

    Returns:
        A decision for whichever option the reply selected, or ``None`` when
        the message doesn't clearly answer the question -- the caller then
        falls through to the normal decision, and the stale clarification is
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
    via_affirmative = False
    if len(words) <= 4 and any(
        f" {surface} " in f" {normalized} " for surface in _AFFIRMATIVE_SURFACES
    ):
        selected = options[0]["intent"]
        via_affirmative = True
    else:
        # Matched against the Turkish label a user could plausibly echo back
        # ("Bir taslak hazırlama isteği."), not the internal English intent
        # name -- that never appears in a Turkish reply, so checking for it
        # only ever produced a false sense of an extra fallback.
        for option in options:
            label = option.get("label") or ""
            if label and normalize(label) in normalized:
                selected = option.get("intent")
                break

    if not selected or selected not in PLAN_BY_INTENT:
        return None

    if via_affirmative:
        chosen_label = next(
            (option["label"] for option in options if option["intent"] == selected), selected
        )
        suffix = f" ({chosen_label} olarak ilerliyorum)"
    else:
        suffix = " (açıklayıcı soruya verilen yanıtla çözüldü)"

    return PlanDecision(
        steps=list(PLAN_BY_INTENT[selected]),
        intent=selected,  # type: ignore[arg-type]
        reasoning=REASONING_BY_INTENT[selected] + suffix,
        source="clarification_resolved",
        confidence=1.0,
        evidence=("clarification.resolved",),
    )


async def classify_intent_with_model(
    llm_client: BaseLLMClient, message: str, document_id: Optional[str]
) -> Intent:
    """Break a fusion tie with a one-label model call.

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

    Args:
        message: The user's message.
        document_id: Storage path of an attached document, when present.
        llm_client: Fast-tier client for the band between ``tau_low`` and
            ``tau_high``. When omitted, that band falls to a clarifying
            question instead of a model call.
        previous_intent: The intent resolved for this thread's previous turn,
            when known -- enables the short-affirmative continuation rule and
            feeds the fusion layer's ``prev_*`` features.
        matcher: Prototype matcher supplying per-label semantic similarity.
            Omitted or unavailable means fusion simply runs without those
            features, exactly as before the semantic layer existed.
        focus: The session's persistent focus. Supplies whether a draft is
            active (gates ``revise``) and any open clarifying question
            (checked first, before fusion runs at all).

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
    lexical = score_intents(message, document_id, previous_intent, has_active_draft)

    compound = _try_compound(lexical)
    if compound is not None:
        logger.info("Plan resolved as compound: %s", compound.steps)
        return compound

    policy = get_policy().intent

    def _fuse(semantic: Optional[dict[str, float]]):
        signals = RouterSignals(
            lexical=lexical,
            semantic=semantic,
            has_document=document_id is not None,
            has_active_draft=has_active_draft,
            previous_intent=previous_intent,
        )
        features = extract_features(message, signals)
        probs = predict_proba(features, ROUTER_WEIGHTS)
        ranked = sorted(probs.items(), key=lambda item: (-item[1], item[0]))
        return probs, ranked

    # Lexical-only fusion first, exactly like the old ladder's cheapest rung:
    # a message the lexical evidence alone already commits to must not pay
    # for an embedding call it doesn't need.
    probs, ranked = _fuse(None)
    top_intent, top_probability = ranked[0]
    source = "fused"

    if top_probability < policy.tau_high and matcher is not None:
        semantic = await matcher.label_similarities(message, "intent")
        if semantic:
            probs, ranked = _fuse(semantic)
            top_intent, top_probability = ranked[0]
            source = "fused_semantic"

    if top_probability >= policy.tau_high:
        logger.info(
            "Plan resolved via %s: intent=%s p=%.3f", source, top_intent, top_probability
        )
        return _fused_decision(top_intent, probs, ranked, lexical, source)

    if top_probability >= policy.tau_low and llm_client is not None:
        intent = await classify_intent_with_model(llm_client, message, document_id)
        logger.info(
            "Fused probability %.3f contested; model broke the tie: intent=%s",
            top_probability,
            intent,
        )
        return PlanDecision(
            steps=list(PLAN_BY_INTENT[intent]),
            intent=intent,
            reasoning=REASONING_BY_INTENT[intent],
            source="model",
            confidence=round(top_probability, 3),
            evidence=tuple(lexical.evidence),
        )

    logger.info(
        "Fused probability %.3f (%s) not decisive enough to act on; asking instead.",
        top_probability,
        top_intent,
    )
    return _build_clarify_decision(ranked)
