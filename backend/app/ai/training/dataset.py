"""Preference-pair compilation -- Faz C3 (#187).

Pure functions only: turns already-resolved feedback rows into
`PreferencePair`s. Deliberately has zero `app.domains` imports, same rule
`app.ai.adapters.company_adapter` documents -- the actual `feedback`/
`drafts` reads live in `app.domains.training.service`, which calls into
this module with plain data, not ORM rows.

Only `explicit_feedback` is compiled today (a 👍/👎 vote whose rated text
could be resolved back to a `DraftModel.content`). The plan's "örtük
sinyaller" (implicit HITL approve/reject/revise trail) are deliberately not
compiled here yet -- see `TrainingSampleModel`'s docstring for why: today's
`drafts.status` records workflow outcome, not a user accept/reject
decision, and inventing a preference label from the wrong field would
mislabel the very data a style adapter is trained from. Reusing the exact
`app.domains.feedback.model.feedback_model.FeedbackModel` docstring's own
rule here: "the model's own prediction is never used as a label" -- so is
an ambiguous status.
"""

import hashlib
from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class FeedbackRecord:
    """One `feedback` vote, with its rated text already resolved (via
    `draft_id` -> `DraftModel.content`, the only durable text store a vote
    can point back to -- see `FeedbackModel`'s docstring on why the vote
    itself never carries the raw text).

    A vote whose text could not be resolved (no `draft_id`, or the draft
    row is gone) is simply never turned into a `FeedbackRecord` by the
    caller -- there is nothing this module can derive a pair from without
    text.
    """

    feedback_id: str
    signal: str  # "like" | "dislike"
    content: str
    draft_id: Optional[str] = None
    correspondence_type: Optional[str] = None
    confidence_score: Optional[float] = None


@dataclass(frozen=True)
class PreferencePair:
    """One row `app.domains.training.service` upserts into
    `TrainingSampleModel`. `chosen`/`rejected` are single-wing for every
    source implemented so far -- one vote is one side of a pair, never
    both (see `TrainingSampleModel`'s docstring); `rejected is None` for a
    like, `chosen is None` for a dislike.
    """

    source: str
    source_feedback_id: Optional[str]
    source_draft_id: Optional[str]
    prompt_context: str
    chosen: Optional[str]
    rejected: Optional[str]
    weight: float
    pair_hash: str


EXPLICIT_FEEDBACK_SOURCE = "explicit_feedback"


def pair_hash(company_id: str, source: str, identity: str) -> str:
    """The identity a re-compile upserts onto. For `explicit_feedback`,
    `identity` is the feedback row's own id: that row's identity is stable
    for its whole lifetime even when its `signal` flips (re-voting updates
    the same row in place, see `FeedbackModel`'s docstring), so recompiling
    after a 👍->👎 flip correctly refreshes `chosen`/`rejected` on the same
    `training_samples` row instead of leaving a stale duplicate behind.
    """
    return hashlib.sha256(f"{company_id}:{source}:{identity}".encode("utf-8")).hexdigest()


def _prompt_context(record: FeedbackRecord) -> str:
    parts: List[str] = []
    if record.correspondence_type:
        parts.append(f"Yazışma türü: {record.correspondence_type}")
    if record.confidence_score is not None:
        parts.append(f"Güven skoru: {record.confidence_score:.0f}")
    return " | ".join(parts)


def compile_pairs_from_feedback(
    company_id: str, records: Iterable[FeedbackRecord]
) -> List[PreferencePair]:
    """Turn resolved feedback votes into preference pairs, one per record."""
    pairs: List[PreferencePair] = []
    for record in records:
        content = record.content.strip()
        if not content:
            continue
        is_like = record.signal == "like"
        pairs.append(
            PreferencePair(
                source=EXPLICIT_FEEDBACK_SOURCE,
                source_feedback_id=record.feedback_id,
                source_draft_id=record.draft_id,
                prompt_context=_prompt_context(record),
                chosen=content if is_like else None,
                rejected=None if is_like else content,
                weight=1.0,
                pair_hash=pair_hash(company_id, EXPLICIT_FEEDBACK_SOURCE, record.feedback_id),
            )
        )
    return pairs
