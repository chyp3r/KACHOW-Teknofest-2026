"""Scores a message against the evidence rules and decides by margin.

The decision is the *margin* between the top two intents, not the top score.
That single choice is what makes the failures the baseline measured fixable:

* A message carrying both a drafting phrase and an analysis phrase produces two
  close scores. A small margin is not a tie to be broken arbitrarily -- it is
  information, and it routes to a compound plan or an escalation rather than to
  whichever rule the old cascade happened to check first.
* A message carrying a domain noun plus a definitional counter-signal
  ("Üst yazı ne demek?") produces a *negative* contribution to draft and a
  positive one to chat, so it resolves to chat without weakening the drafting
  phrases that every genuine request depends on.

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


def _fires(rule: EvidenceRule, normalized: str, has_document: bool) -> bool:
    """Report whether a rule applies to this message."""
    if rule.requires_document is not None and rule.requires_document is not has_document:
        return False
    return any(surface in normalized for surface in rule.surfaces)


def _looks_like_question(raw: str, normalized: str) -> bool:
    """Heuristically decide whether the message asks something."""
    if "?" in raw:
        return True
    padded = f" {normalized} "
    return any(f" {marker.strip()} " in padded for marker in QUESTION_SURFACES)


def score_intents(
    message: str, document_id: Optional[str], previous_intent: Optional[str] = None
) -> IntentScores:
    """Accumulate evidence for every intent.

    Args:
        message: The user's message.
        document_id: Storage path of an attached document, when present.
        previous_intent: The intent resolved for the previous turn, when known.

    Returns:
        The accumulated scores and the ids of every rule that fired.
    """
    normalized = normalize(message)
    has_document = document_id is not None
    result = IntentScores()

    if not normalized:
        result.scores["chat"] = 10.0
        result.evidence.append("chat.empty_message")
        return result

    definitional = False
    for rule in ALL_RULES:
        if not _fires(rule, normalized, has_document):
            continue
        result.scores[rule.intent] = result.scores.get(rule.intent, 0.0) + rule.weight
        result.evidence.append(rule.id)
        if rule.id == "chat.definitional_question":
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
    # Suppressed when the message is a greeting or a courtesy: "İyi akşamlar,
    # yarın devam ederiz" after a draft turn contains "devam" but is a farewell,
    # and reading it as consent produced a whole drafting run on the old
    # resolver. A sign-off is the one place "devam" means the opposite of
    # "continue now".
    signing_off = {"chat.greeting", "chat.courtesy"}.intersection(result.evidence)
    if (
        previous_intent in CONTINUABLE_INTENTS
        and not signing_off
        and len(words) <= 6
        and any(f" {surface} " in f" {normalized} " for surface in CONTINUATION_SURFACES)
    ):
        result.scores[previous_intent] = (
            result.scores.get(previous_intent, 0.0) + WEIGHT_HINT * 3
        )
        result.evidence.append(f"{previous_intent}.continuation")

    # A question with a document attached leans toward document Q&A -- a hint,
    # not a gate. The old resolver made this a branch, which is why "Sen neler
    # yapabilirsin?" with a document attached became a document question.
    #
    # Weighted at DOMAIN rather than HINT so it clears the presence floor on its
    # own: "Evrakın konusu nedir?" carries no other document phrase, and a hint
    # too weak to be a candidate would send every such question to the model.
    if has_document and _looks_like_question(message, normalized):
        result.scores["document_qa"] = (
            result.scores.get("document_qa", 0.0) + WEIGHT_DOMAIN
        )
        result.evidence.append("document_qa.question_with_document")

    # A very short message with nothing attached is conversational filler --
    # unless it is a continuation, in which case brevity is the *same* evidence
    # counted twice. "evet, hazırla" is short precisely because it is an
    # affirmative, and letting both signals fire left the two scores close
    # enough to escalate a message whose meaning is not in doubt.
    continued = f"{previous_intent}.continuation" in result.evidence
    if not has_document and not continued and len(words) <= 4:
        result.scores["chat"] = result.scores.get("chat", 0.0) + WEIGHT_HINT * 2
        result.evidence.append("chat.short_message")

    # Applied last, after every document_qa signal has been accumulated: a
    # question about *this conversation* is not a question about the document,
    # so document phrases in it are not evidence -- they are the subject the
    # user is recalling.
    #
    # Invalidating document_qa rather than outscoring it is what makes two rules
    # the repo already relies on compatible. Memory recall must beat document_qa
    # ("Bu belgede kaç madde vardı, hatırlıyor musun?"), while an explicit
    # drafting request must still beat memory recall ("Az önce taslak
    # hazırlamanı istemiştim, şimdi hazırla"). No single weight for the recall
    # rule satisfies both -- one needs it above 4.4, the other below 3.4 --
    # but removing the invalid evidence satisfies both at once.
    if "chat.memory_recall" in result.evidence and "document_qa" in result.scores:
        result.scores["document_qa"] += WEIGHT_COUNTER
        result.evidence.append("document_qa.memory_recall_counter")

    return result
