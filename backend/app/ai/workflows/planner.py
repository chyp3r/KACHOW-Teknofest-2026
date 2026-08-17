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
policy is:

* At or above ``tau_high``, **and** backed by more than a structural filler
  (see ``_WEAK_EVIDENCE_IDS``) -- committed outright (``source="fused"`` /
  ``"fused_semantic"``). A win supported only by "the message was short" or
  "a document happens to be attached" is a win by default, not by evidence,
  and is treated as contested instead.
* Otherwise, whenever a fast-tier model is available -- asked to break the
  tie (``source="model"``), now regardless of how low the fused probability
  fell. A thin fused signal is exactly the case a model call earns its keep;
  it stopped being a reason to skip the call once the ladder became a
  fusion (skipping below ``tau_low`` was a leftover from the old rung-order
  design, where a low *lexical* margin meant nothing else had run yet --
  here every signal already has). The model's own ``unclear`` verdict is
  only honored as a genuine tie -- and turned into a clarifying question --
  when the fused top two are within ``clarify_margin`` of each other *and*
  the fused top probability is itself below ``tau_low``; otherwise the
  fused top intent wins the tie the model declined to break
  (``source="model_unclear"``).
* No model available at all (only in tests and matcher/LLM-less
  deployments) -- ``tau_low`` still gates a direct clarify, unchanged from
  before.

One thing runs *after* fusion and can override any of it: the domain scope
gate (:mod:`app.ai.workflows.scope`). Fusion answers which flow a message
wants; it has no way to answer whether the message wants any flow at all,
and every layer here would confidently route "Çiğköfte kampanyası için bir
metin yaz" to ``draft`` because, as a matter of intent, that is exactly what
it is. ``resolve_plan`` therefore resolves the intent first and admits it
second -- see ``_apply_scope_gate``.

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
import time
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, Optional

from pydantic import BaseModel, Field

from app.observability.ai_metrics import ROUTER_STAGE_DURATION

from app.ai.context.compress import truncate_with_marker
from app.ai.llms.base import BaseLLMClient
from app.ai.policy import get_policy
from app.ai.policy.router_weights import ROUTER_WEIGHTS
from app.ai.session.focus import SessionFocus
from app.ai.workflows.intent_rules import CONTINUATION_SURFACES, Intent
from app.ai.workflows.intent_scorer import COMPOUND_FLOOR, IntentScores, normalize, score_intents
from app.ai.workflows.router_features import RouterSignals, extract_features
from app.ai.workflows.router_fusion import predict_proba
from app.ai.workflows.scope import ScopeVerdict, resolve_scope

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
#: ``refuse`` is a single deterministic step that renders the capability
#: manifest and ends the turn (see ``planning_graph._step_refuse``). It costs
#: no model call on purpose -- a refusal must not be a generation, or the
#: model that was just told not to write the off-topic text gets one more
#: opportunity to write it anyway.
#: `transfer` (Faz 4, #201) is deliberately NOT one of these -- it is never
#: a resolvable top-level intent at all. It is a tool the assist step's own
#: model may call mid-conversation (`app.ai.tools.transfer_tools.
#: build_transfer_tools`, wired in `_run_assist`), the same way
#: `search_document` is; the planner never routes a message to it directly.
#: `transfer_execute` (the one step this can still lead to, once a human
#: confirms) is appended to `plan_steps` dynamically by `_step_assist` when
#: the tool actually produces a pending proposal -- see
#: `step_graph.STEP_SPECS`'s own entry for it.
PLAN_BY_INTENT: dict[str, list[str]] = {
    "draft": ["classification", "brief", "draft", "routing"],
    "analyze": ["classification"],
    "assist": ["assist"],
    "revise": ["revise"],
    "clarify": ["clarify"],
    "refuse": ["refuse"],
}

REASONING_BY_INTENT: dict[str, str] = {
    "draft": "Resmî yazı talebi tespit edildi: evrak analizi, taslak üretimi ve birim yönlendirmesi çalıştırılacak.",
    "analyze": "Evrak analizi talebi tespit edildi: sınıflandırma ve uygunluk denetimi çalıştırılacak.",
    "assist": "Genel bir soru veya belge hakkında bir soru tespit edildi: asistan yanıtı hazırlanacak.",
    "revise": "Mevcut taslakta bir revizyon talebi tespit edildi: hedefli düzeltme çalıştırılacak.",
    "clarify": "İstek belirsiz olduğu için kullanıcıya açıklayıcı bir soru soruldu.",
    "refuse": "İstek sistemin görev alanı dışında kaldığı için hiçbir üretim akışı çalıştırılmadı.",
}

#: Canonical execution order, used to merge two intents' step lists without
#: letting the merge invent an ordering of its own. ``clarify`` is absent on
#: purpose: it never appears in a compound plan (see ``COMPOUND_PAIR``).
STEP_ORDER: tuple[str, ...] = (
    "classification",
    "brief",
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

#: Evidence ids that are structural fillers, not intent-specific signal --
#: "a question landed while a document happens to be attached" describes the
#: message's shape, not what it asked for, and says nothing about whether a
#: *different* intent (e.g. `revise`, if a draft is also open) was the real
#: one being asked about. See `intent_scorer.score_intents`'s
#: `assist.question_with_document` rule. A fused decision whose winning
#: intent is backed *only* by ids in this set is escalated to the model
#: instead of committed outright -- see `_has_only_weak_evidence`.
#:
#: `assist.short_message` is deliberately absent: it already can't fire
#: while a draft is open (`intent_scorer.score_intents` gates it on
#: `not has_active_draft`, which is the one case where its brevity used to
#: outscore a genuine short revise instruction like "giriş kısmını
#: yumuşat"). With no draft open and nothing else attached, a short message
#: backed only by its own brevity -- a bare "Evet" after a non-continuable
#: turn, say -- has no competing reading left to lose to, so there is
#: nothing left for this gate to protect against; escalating it anyway would
#: just turn an unambiguous "nothing else applies" default into an
#: unnecessary question.
_WEAK_EVIDENCE_IDS = frozenset({"assist.question_with_document"})

#: Confidence reported for a model-broken tie and for the safe default used
#: when the model call itself fails. Not the fusion layer's own
#: `top_probability` (that number is fusion's uncertainty, the exact thing
#: that made this a tie in the first place -- reporting it back out as the
#: *model's* confidence would be circular) and not measured against real
#: model output either, since that needs a live Ollama call the default,
#: fully offline `make eval` deliberately never makes (see
#: `evaluation.harness.intent_suite`'s module docstring). `make eval-llm`
#: (`evaluation/harness/intent_suite.py::run_with_model`) is the optional,
#: opt-in measurement this constant should eventually be replaced with.
_MODEL_CONFIDENCE = 0.75

#: Raw turns handed to the fast-tier model call, most recent last. Small on
#: purpose -- this is a label call, not the assist step's own generation, so
#: it only needs enough of the conversation's shape to disambiguate a short
#: message ("selam" after a revise turn vs. after silence), not the full
#: window the assist step budgets for.
_MODEL_HISTORY_TURNS = 4


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
        scope_reason: Which domain-admission rule settled this turn (see
            ``app.ai.workflows.scope.ScopeReason``). Recorded on *every*
            decision, not only refusals, so "why did this run" is as
            traceable as "why was this refused".
    """

    steps: list[str]
    intent: Intent
    reasoning: str
    source: str
    confidence: float = 1.0
    evidence: tuple[str, ...] = ()
    alternatives: tuple[tuple[str, float], ...] = ()
    clarification: Optional[dict[str, Any]] = None
    scope_reason: str = ""


class IntentOutput(BaseModel):
    """Single-label intent classification, used only for genuinely contested messages.

    Five labels, not four: ``unclear`` is a real, first-class answer, not an
    error path. Before this the model had only ``draft``/``analyze``/``assist``
    to choose from -- asked about a message the fusion layer already found
    contested, it had no way to say "I'm not sure either" and had to force a
    guess into one of three boxes, one of which (``revise``) it couldn't even
    name.
    """

    intent: Literal["draft", "analyze", "assist", "revise", "unclear"] = Field(
        description=(
            "Kullanıcının niyeti. draft: resmi yazı/taslak hazırlanması isteniyor. "
            "analyze: evrakın analiz edilmesi isteniyor. "
            "revise: mevcut (aktif) taslakta bir değişiklik isteniyor. "
            "assist: yukarıdakilerin hiçbiri; genel sohbet veya yüklü bir belge hakkında soru. "
            "unclear: bunlardan hangisi olduğu senin için de belirsizse, tahmin etme -- "
            "bunu seç."
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


def _has_only_weak_evidence(intent: str, lexical: IntentScores, has_active_draft: bool) -> bool:
    """Whether ``intent``'s win rests on nothing but structural filler.

    Args:
        intent: The fusion layer's winning intent.
        lexical: The message's lexical evidence.
        has_active_draft: Whether a draft is open this turn. The only reason
            ``assist.question_with_document`` is worth distrusting is that it
            might be drowning out a `revise` reading of the same message
            ("Bu daha iyi mi görünüyor?" with both a document *and* an open
            draft) -- without a draft open there is nothing else the message
            could plausibly mean, so a bare document-question win is exempted
            outright rather than sent on an escalation round trip with
            nothing to resolve. Same reasoning `intent_scorer.score_intents`
            already applies to `assist.short_message` by gating it on
            ``not has_active_draft`` at the rule level instead.

    Returns:
        True when every lexical rule that fired *for this intent* is in
        ``_WEAK_EVIDENCE_IDS`` -- including the case where none fired at all,
        meaning the win came from the semantic layer or the fusion model's
        prior alone, weaker still than a filler rule.
    """
    if intent == "assist" and not has_active_draft:
        return False
    strong = [
        rule_id
        for rule_id in lexical.evidence
        if rule_id.startswith(f"{intent}.") and rule_id not in _WEAK_EVIDENCE_IDS
    ]
    return not strong


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
    llm_client: BaseLLMClient,
    message: str,
    document_id: Optional[str],
    focus: Optional[SessionFocus] = None,
    previous_intent: Optional[str] = None,
    history: Optional[list[dict[str, str]]] = None,
) -> str:
    """Break a fusion tie with a one-label model call.

    Args:
        llm_client: Fast-tier LLM client.
        message: The user's message.
        document_id: Storage path of an attached document, when present.
        focus: The session's persistent focus, when known -- supplies whether
            a draft is already open and what kind (plus an excerpt of its
            text and the session's accumulated objective), context a bare
            label call otherwise has no way to see. The fusion layer sees
            `has_active_draft` too, as a feature value, but this prompt has
            to spell the same fact out in words -- and, unlike the fusion
            layer, can also show *what* the draft says, which is exactly
            what a message like "son cümle bana biraz sert geldi" needs to
            resolve against.
        previous_intent: The intent resolved for the previous turn, when
            known.
        history: The last few raw turns of this conversation, oldest first,
            when known. Now that this call is the fallback for *every*
            fusion-contested message rather than a narrow middle band, it
            needs the same kind of conversational grounding the assist step
            already gets -- a bare "selam" or "yarın devam ederiz" only reads
            as small talk in light of what the turn before it was.

    Returns:
        One of ``PLAN_BY_INTENT``'s keys, or ``"unclear"``/``"model_failed"``
        -- two distinct non-intents the caller must handle before treating the
        result as a plan: ``"unclear"`` is the model's own considered
        judgement that it doesn't know either (see ``IntentOutput``);
        ``"model_failed"`` means the call itself broke (timeout, malformed
        output, retries exhausted) and never produced a judgement at all.
        Conflating the two would hide a real outage behind the same label a
        model's honest uncertainty produces.
    """
    from app.ai.agents.base import BaseAgent

    agent = BaseAgent(
        llm_client=llm_client,
        name="IntentClassifier",
        description="Classifies a user message into one of five workflow intents.",
        system_prompt=(
            "Kullanıcı mesajını beş niyetten birine ata. Yalnızca yapılandırılmış "
            "JSON döndür, açıklama yazma.\n"
            "- draft: resmî yazı, cevap yazısı, üst yazı veya taslak hazırlanması isteniyor.\n"
            "- analyze: bir evrakın analiz edilmesi, sınıflandırılması veya eksiklerinin "
            "bulunması isteniyor.\n"
            "- revise: aşağıda 'açık bir taslak var' diye belirtilmişse, o taslakta bir "
            "değişiklik isteniyor.\n"
            "- assist: yukarıdakilerin hiçbiri; genel sohbet, sistem hakkında soru veya "
            "yüklü bir belgenin içeriği hakkında soru.\n"
            "- unclear: yukarıdakilerden hangisi olduğundan emin değilsen, tahmin etme."
        ),
    )

    active_draft = focus.active_draft if focus else None
    objective = (focus.objective if focus else "") or ""
    context_lines = [
        f"Sisteme yüklü bir belge var mı: {'evet' if document_id else 'hayır'}",
        (
            f"Açık bir taslak var, türü: {active_draft.correspondence_type}.\n"
            f"Taslağın başı: \"{truncate_with_marker(active_draft.text, 60)}\""
            if active_draft is not None
            else "Açık (üzerinde çalışılan) bir taslak yok"
        ),
        f"Önceki turun niyeti: {previous_intent or 'yok'}",
    ]
    if objective:
        context_lines.append(f"Bu oturumda kullanıcının amacı (özet): {objective}")

    if history:
        recent = history[-_MODEL_HISTORY_TURNS:]
        turns_text = "\n".join(
            f"{turn.get('role')}: {truncate_with_marker(turn.get('content', ''), 40)}"
            for turn in recent
        )
        context_lines.append(f"Son konuşma turları:\n{turns_text}")

    context_lines.append(f'Son mesaj: "{message}"')
    prompt = "\n".join(context_lines) + "\n\nSon mesajın niyetini belirle."

    try:
        result: IntentOutput = await agent.run_structured(
            messages=prompt,
            response_model=IntentOutput,
            temperature=0.0,
            max_retries=1,
        )
        return result.intent
    except Exception:
        logger.warning("Intent classification failed.")
        return "model_failed"


def _clarify_or_fallback(
    ranked: list[tuple[str, float]],
    probs: dict[str, float],
    lexical: IntentScores,
    focus: Optional[SessionFocus],
) -> PlanDecision:
    """Ask a clarifying question, unless the previous turn already asked one.

    A user who didn't answer the last clarifying question clearly (see
    ``_try_resolve_pending_clarification``) and then sent another message the
    decision layer also finds ambiguous would otherwise be asked a second
    question in a row -- annoying on its own, and indistinguishable to the
    user from the system having ignored their first answer. Committing to the
    fused top intent is the better failure mode: wrong sometimes, but never a
    conversation that only ever asks.

    Args:
        ranked: Intents sorted by fused probability, highest first.
        probs: The fused probability for every intent.
        lexical: The message's lexical evidence.
        focus: The session's persistent focus, when known.

    Returns:
        A clarifying decision, or a committed decision for the fused top
        intent when the previous turn was already a clarify.
    """
    if focus is not None and focus.last_intent == "clarify":
        top_intent, _ = ranked[0]
        logger.info(
            "Previous turn was already a clarify; committing to the fused top "
            "intent instead of asking a second time in a row: intent=%s",
            top_intent,
        )
        return _fused_decision(top_intent, probs, ranked, lexical, "clarify_repeat_guard")
    return _build_clarify_decision(ranked)


def _apply_scope_gate(decision: PlanDecision, verdict: ScopeVerdict) -> PlanDecision:
    """Fold a scope verdict into an already-resolved plan.

    Args:
        decision: The intent-resolved plan.
        verdict: The domain-admission verdict for the same message.

    Returns:
        ``decision`` with ``scope_reason`` recorded when admitted; a
        single-step ``refuse`` plan when not. The original intent is kept in
        ``evidence`` (``scope.refused_intent:<name>``) rather than discarded
        -- a refusal that loses what it refused is unreviewable, and the
        offline harness scores refusals against the intent they replaced.
    """
    if verdict.in_scope:
        return decision._replace(scope_reason=verdict.reason)

    return PlanDecision(
        steps=list(PLAN_BY_INTENT["refuse"]),
        intent="refuse",  # type: ignore[arg-type]
        reasoning=REASONING_BY_INTENT["refuse"],
        source=f"scope_{verdict.source}",
        confidence=decision.confidence,
        evidence=(*decision.evidence, f"scope.refused_intent:{decision.intent}"),
        alternatives=decision.alternatives,
        scope_reason=verdict.reason,
    )


async def resolve_plan(
    message: str,
    document_id: Optional[str],
    llm_client: Optional[BaseLLMClient] = None,
    previous_intent: Optional[str] = None,
    matcher: Optional["PrototypeMatcher"] = None,
    focus: Optional[SessionFocus] = None,
    history: Optional[list[dict[str, str]]] = None,
) -> PlanDecision:
    """Resolve the execution plan, then admit it (or refuse it) by scope.

    Intent resolution (``_resolve_intent``) and domain admission
    (``app.ai.workflows.scope``) are deliberately two passes over the same
    message rather than one enlarged classifier: "which flow does this want"
    and "does this want any flow" have different evidence, different failure
    modes, and different costs to get wrong. Merging them is what a fifth
    intent label would do, and a fifth label competes for softmax mass with
    the four real ones instead of vetoing them.

    Args and Returns are as ``_resolve_intent``'s, with one addition: the
    returned decision may be a ``refuse`` plan regardless of what the intent
    layer concluded.
    """
    decision = await _resolve_intent(
        message,
        document_id,
        llm_client=llm_client,
        previous_intent=previous_intent,
        matcher=matcher,
        focus=focus,
        history=history,
    )

    # A resolved clarifying question is the user answering *us*; re-admitting
    # it would re-litigate a turn whose scope was already settled when the
    # question was asked.
    if decision.source == "clarification_resolved":
        return decision._replace(scope_reason="clarification_resolved")

    _scope_start = time.perf_counter()
    verdict = await resolve_scope(
        message,
        decision.intent,
        has_document=document_id is not None,
        has_active_draft=bool(focus and focus.active_draft is not None),
        llm_client=llm_client,
    )
    ROUTER_STAGE_DURATION.labels(stage="scope").observe(time.perf_counter() - _scope_start)

    if not verdict.in_scope:
        logger.info(
            "Request refused as out of domain: intent=%s reason=%s (%s)",
            decision.intent,
            verdict.reason,
            verdict.detail,
        )
    return _apply_scope_gate(decision, verdict)


async def _resolve_intent(
    message: str,
    document_id: Optional[str],
    llm_client: Optional[BaseLLMClient] = None,
    previous_intent: Optional[str] = None,
    matcher: Optional["PrototypeMatcher"] = None,
    focus: Optional[SessionFocus] = None,
    history: Optional[list[dict[str, str]]] = None,
) -> PlanDecision:
    """Resolve which of the system's flows a message wants.

    Args:
        message: The user's message.
        document_id: Storage path of an attached document, when present.
        llm_client: Fast-tier client consulted whenever fusion doesn't commit
            outright (``tau_high`` and, since a filler-only win isn't enough
            on its own, the evidence check next to it). When omitted, that
            same case falls to a clarifying question instead of a model call.
        previous_intent: The intent resolved for this thread's previous turn,
            when known -- enables the short-affirmative continuation rule and
            feeds the fusion layer's ``prev_*`` features.
        matcher: Prototype matcher supplying per-label semantic similarity.
            Omitted or unavailable means fusion simply runs without those
            features, exactly as before the semantic layer existed.
        focus: The session's persistent focus. Supplies whether a draft is
            active (gates ``revise``) and any open clarifying question
            (checked first, before fusion runs at all).
        history: This thread's raw prior turns, oldest first, when known --
            forwarded to ``classify_intent_with_model`` unchanged. Fusion
            itself never reads it (only ``previous_intent`` feeds the fused
            features); it exists solely so the model call escalation has the
            same conversational grounding the assist step gets.

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
    _lexical_start = time.perf_counter()
    lexical = score_intents(message, document_id, previous_intent, has_active_draft)
    ROUTER_STAGE_DURATION.labels(stage="lexical").observe(time.perf_counter() - _lexical_start)

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
        _semantic_start = time.perf_counter()
        semantic = await matcher.label_similarities(message, "intent")
        ROUTER_STAGE_DURATION.labels(stage="semantic").observe(
            time.perf_counter() - _semantic_start
        )
        if semantic:
            probs, ranked = _fuse(semantic)
            top_intent, top_probability = ranked[0]
            source = "fused_semantic"

    # The weak-evidence gate only applies to a lexical-only commit: once the
    # semantic pass has run and moved the needle (`source == "fused_semantic"`),
    # the embedding similarity *is* the real signal a filler rule is a stand-in
    # for elsewhere, and second-guessing it here would just be a slower way of
    # ignoring the semantic layer's own vote.
    weak = source == "fused" and _has_only_weak_evidence(top_intent, lexical, has_active_draft)
    if top_probability >= policy.tau_high and not weak:
        logger.info(
            "Plan resolved via %s: intent=%s p=%.3f", source, top_intent, top_probability
        )
        return _fused_decision(top_intent, probs, ranked, lexical, source)

    if llm_client is not None:
        _model_start = time.perf_counter()
        result = await classify_intent_with_model(
            llm_client,
            message,
            document_id,
            focus=focus,
            previous_intent=previous_intent,
            history=history,
        )
        ROUTER_STAGE_DURATION.labels(stage="model").observe(time.perf_counter() - _model_start)

        if result == "model_failed":
            logger.warning(
                "Fused probability %.3f contested; model call failed, defaulting to assist.",
                top_probability,
            )
            return PlanDecision(
                steps=list(PLAN_BY_INTENT["assist"]),
                intent="assist",
                reasoning=REASONING_BY_INTENT["assist"],
                source="model_failed",
                confidence=_MODEL_CONFIDENCE,
                evidence=tuple(lexical.evidence),
            )

        if result == "unclear" or result not in PLAN_BY_INTENT:
            top_two_margin = ranked[0][1] - ranked[1][1]
            if top_probability < policy.tau_low and top_two_margin < policy.clarify_margin:
                logger.info(
                    "Fused probability %.3f contested; model was unclear too and the "
                    "top two intents are within %.3f of each other. Asking instead.",
                    top_probability,
                    top_two_margin,
                )
                return _clarify_or_fallback(ranked, probs, lexical, focus)
            logger.info(
                "Model was unclear, but the fused top intent (%s, p=%.3f, margin=%.3f) "
                "already leads clearly; committing to it instead of asking again.",
                top_intent,
                top_probability,
                top_two_margin,
            )
            return _fused_decision(top_intent, probs, ranked, lexical, "model_unclear")

        logger.info(
            "Fused probability %.3f contested; model broke the tie: intent=%s",
            top_probability,
            result,
        )
        return PlanDecision(
            steps=list(PLAN_BY_INTENT[result]),
            intent=result,  # type: ignore[arg-type]
            reasoning=REASONING_BY_INTENT[result],
            source="model",
            confidence=_MODEL_CONFIDENCE,
            evidence=tuple(lexical.evidence),
        )

    logger.info(
        "Fused probability %.3f (%s) not decisive enough to act on and no model "
        "available; asking instead.",
        top_probability,
        top_intent,
    )
    return _clarify_or_fallback(ranked, probs, lexical, focus)
