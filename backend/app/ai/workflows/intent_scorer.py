"""Scores a message against the evidence rules and decides by margin.

The decision is the *margin* between the top two intents, not the top score.
That single choice is what makes the failures the baseline measured fixable:

* A message carrying both a drafting phrase and an analysis phrase produces two
  close scores. A small margin is not a tie to be broken arbitrarily -- it is
  information, and it routes to a compound plan or an escalation rather than to
  whichever rule the old cascade happened to check first.
* A message carrying a domain noun plus a definitional counter-signal
  ("Üst yazı ne demek?") produces a *negative* contribution to draft and a
  positive one to assist, so it resolves to assist without weakening the
  drafting phrases that every genuine request depends on.

Everything here is arithmetic over a table -- no model call, sub-millisecond,
and reproducible. Where the previous resolver escalated every message it could
not pattern-match, this one escalates only where the evidence is genuinely
balanced or genuinely absent, which is why the escalation rate falls even as
accuracy rises.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from app.ai.policy import get_policy
from app.ai.workflows.intent_rules import (
    ALL_RULES,
    CONTINUABLE_INTENTS,
    CONTINUATION_SURFACES,
    QUESTION_SURFACES,
    WEIGHT_COUNTER,
    WEIGHT_DOMAIN,
    WEIGHT_HINT,
    EvidenceRule,
    Intent,
)

logger = logging.getLogger(__name__)

_INTENT_POLICY = get_policy().intent

#: Minimum lead the top intent needs over the runner-up to be decisive.
DECISIVE_MARGIN = _INTENT_POLICY.decisive_margin

#: Minimum score for an intent to count as genuinely present at all. Below this
#: an intent is noise, not a candidate -- without a floor, two rules scoring
#: 0.1 and 0.0 would read as a confident decision.
PRESENCE_FLOOR = _INTENT_POLICY.presence_floor

#: With the margin below `DECISIVE_MARGIN`, both intents at or above this are
#: treated as a compound request rather than an ambiguity to escalate.
COMPOUND_FLOOR = _INTENT_POLICY.compound_floor

#: Score used to convert a margin into a [0, 1] confidence. A lead of this much
#: reads as full confidence; the value is the observed spread between a clean
#: single-rule hit and a contested one.
CONFIDENCE_SCALE = _INTENT_POLICY.confidence_scale

_TURKISH_MAP = str.maketrans(
    {
        "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i",
        "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
    }
)


@dataclass
class IntentScores:
    """The full scoring outcome for one message.

    Attributes:
        scores: Intent -> accumulated weight.
        evidence: Rule ids that fired, in rule-table order.
        ranked: Intents sorted by score, highest first.
    """

    scores: dict[str, float] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)

    @property
    def ranked(self) -> list[tuple[str, float]]:
        """Intents by score, highest first, ties broken by name for stability."""
        return sorted(self.scores.items(), key=lambda item: (-item[1], item[0]))

    @property
    def margin(self) -> float:
        """Lead of the top intent over the runner-up. 0.0 when fewer than two."""
        ranked = self.ranked
        if len(ranked) < 2:
            return ranked[0][1] if ranked else 0.0
        return ranked[0][1] - ranked[1][1]

    @property
    def confidence(self) -> float:
        """Margin mapped into [0, 1]."""
        return max(0.0, min(1.0, self.margin / CONFIDENCE_SCALE))


def normalize(text: str) -> str:
    """Fold Turkish text to lowercase ASCII for phrase matching.

    Args:
        text: Raw user text.

    Returns:
        Lowercase ASCII with punctuation collapsed to single spaces.
    """
    folded = (text or "").translate(_TURKISH_MAP)
    folded = unicodedata.normalize("NFKD", folded)
    ascii_text = folded.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


def _compile_surface(surface: str) -> re.Pattern:
    """Compile one rule surface with a left word boundary, no right boundary.

    A left boundary alone fixes the concrete false positive ("uzat" inside
    "uzatma") without pretending to Turkish morphology: the language is
    agglutinative, so a legitimate hit routinely continues past the bare
    surface ("kısaltır mısın" for "kisalt", "revize edelim" for "revize et"
    only if the rule surface itself ends where the suffix begins). The right
    side stays open on purpose.
    """
    return re.compile(r"(?<![a-z0-9])" + re.escape(surface))


#: One compiled pattern per surface, keyed by rule id and built once at
#: import time rather than per call -- `ALL_RULES` is a fixed module-level
#: tuple, so there is nothing to invalidate.
_SURFACE_PATTERNS: dict[str, tuple[re.Pattern, ...]] = {
    rule.id: tuple(_compile_surface(surface) for surface in rule.surfaces)
    for rule in ALL_RULES
}


def _fires(
    rule: EvidenceRule, normalized: str, has_document: bool, has_active_draft: bool
) -> bool:
    """Report whether a rule applies to this message."""
    if rule.requires_document is not None and rule.requires_document is not has_document:
        return False
    if (
        rule.requires_active_draft is not None
        and rule.requires_active_draft is not has_active_draft
    ):
        return False
    return any(pattern.search(normalized) for pattern in _SURFACE_PATTERNS[rule.id])


def looks_like_question(raw: str, normalized: str) -> bool:
    """Heuristically decide whether the message asks something.

    Public (not `_`-prefixed): reused by `router_features.extract_features`
    as one of the fusion layer's structural signals, not just internally by
    `score_intents`.
    """
    if "?" in raw:
        return True
    padded = f" {normalized} "
    return any(f" {marker.strip()} " in padded for marker in QUESTION_SURFACES)


def score_intents(
    message: str,
    document_id: Optional[str],
    previous_intent: Optional[str] = None,
    has_active_draft: bool = False,
) -> IntentScores:
    """Accumulate evidence for every intent.

    Args:
        message: The user's message.
        document_id: Storage path of an attached document, when present.
        previous_intent: The intent resolved for the previous turn, when known.
        has_active_draft: Whether `SessionFocus.active_draft` is set --
            gates `revise`'s rules the same way `document_id` gates a
            document-only rule (see `EvidenceRule.requires_active_draft`).

    Returns:
        The accumulated scores and the ids of every rule that fired.
    """
    normalized = normalize(message)
    has_document = document_id is not None
    result = IntentScores()

    if not normalized:
        result.scores["assist"] = 10.0
        result.evidence.append("assist.empty_message")
        return result

    definitional = False
    for rule in ALL_RULES:
        if not _fires(rule, normalized, has_document, has_active_draft):
            continue
        result.scores[rule.intent] = result.scores.get(rule.intent, 0.0) + rule.weight
        result.evidence.append(rule.id)
        if rule.id == "assist.definitional_question":
            definitional = True

    # A definitional question is *about* a concept, so the domain noun that
    # triggered draft/analyze is describing the topic rather than requesting
    # the action. Subtracting here rather than lowering the noun's own weight
    # keeps every genuine request at full strength.
    if definitional:
        for intent in ("draft", "analyze"):
            if intent in result.scores:
                result.scores[intent] += WEIGHT_COUNTER
                result.evidence.append(f"{intent}.definitional_counter")

    words = normalized.split()

    # A short affirmative continues the previous turn's intent. Bounded by
    # length so "evet, ama önce şunu incele" is scored on its content instead.
    #
    # Suppressed when the message is a greeting, a courtesy, or a farewell:
    # "İyi akşamlar, yarın devam ederiz" after a draft turn contains "devam"
    # but is a sign-off, and reading it as consent produced a whole drafting
    # run on the old resolver. A sign-off is the one place "devam" means the
    # opposite of "continue now".
    #
    # Also suppressed when the message is itself a question: "Peki sence bu
    # yeterli mi" after a draft turn contains "peki" (a continuation surface)
    # but is asking the assistant's opinion, not confirming the next action --
    # scoring it as draft continuation ran a whole second drafting pipeline
    # off a question the user expected a conversational answer to.
    signing_off = {"assist.greeting", "assist.courtesy", "assist.farewell"}.intersection(
        result.evidence
    )
    if (
        previous_intent in CONTINUABLE_INTENTS
        and not signing_off
        and len(words) <= 6
        and not looks_like_question(message, normalized)
        and any(f" {surface} " in f" {normalized} " for surface in CONTINUATION_SURFACES)
    ):
        result.scores[previous_intent] = (
            result.scores.get(previous_intent, 0.0) + WEIGHT_HINT * 3
        )
        result.evidence.append(f"{previous_intent}.continuation")

    # A question with a document attached leans toward `assist` -- a hint, not
    # a gate. The old resolver made this a branch, which is why "Sen neler
    # yapabilirsin?" with a document attached became a document question.
    #
    # Weighted at DOMAIN rather than HINT so it clears the presence floor on its
    # own: "Evrakın konusu nedir?" carries no other document phrase, and a hint
    # too weak to be a candidate would send every such question to the model.
    #
    # Before `chat` and `document_qa` merged into one `assist` bucket, this
    # rule's positive signal for document_qa had to be defended against two
    # counter-signals below (a memory-recall question, a politely-phrased
    # request) that argued the message was really `chat`. Both readings now
    # land on the same intent, so there is nothing left to arbitrate -- the
    # softener and memory-recall counters that used to run here are gone, not
    # renamed, because their sole purpose was resolving a tension this merge
    # eliminated.
    if has_document and looks_like_question(message, normalized):
        result.scores["assist"] = (
            result.scores.get("assist", 0.0) + WEIGHT_DOMAIN
        )
        result.evidence.append("assist.question_with_document")

    # A very short message with nothing attached is conversational filler --
    # unless it is a continuation, in which case brevity is the *same* evidence
    # counted twice. "evet, hazırla" is short precisely because it is an
    # affirmative, and letting both signals fire left the two scores close
    # enough to escalate a message whose meaning is not in doubt.
    #
    # Also withheld while a draft is open: with nothing else attached, a short
    # message is ordinarily filler, but with an active draft it is the single
    # most common shape a targeted revision instruction takes ("giriş kısmını
    # yumuşat" is four words). Padding `assist` here let that brevity alone
    # outscore `revise`'s own explicit rules; `REVISE_RULES` already gates on
    # `requires_active_draft`, so there is nothing left for this hint to
    # arbitrate once a draft is open.
    continued = f"{previous_intent}.continuation" in result.evidence
    if not has_document and not has_active_draft and not continued and len(words) <= 4:
        result.scores["assist"] = result.scores.get("assist", 0.0) + WEIGHT_HINT * 2
        result.evidence.append("assist.short_message")

    return result
