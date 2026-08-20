"""Shared "best attempt wins" bookkeeping for the draft and revise repair loops.

Both loops (``draft_graph``'s writer -> verify -> revise -> writer, and
``revise_graph``'s rewrite -> verify -> repair -> rewrite) can run several
attempts against the same turn. Before this module, whichever attempt
happened to finish *last* was always what shipped -- even when:

- An earlier attempt scored higher and a later repair pass, in fixing one
  defect, introduced a worse one (a common failure mode of a small model
  asked to edit its own output). The attempt budget then runs out with a
  strictly worse draft in hand than the turn already had.
- A repair pass crashed or timed out outright, discarding a perfectly good
  earlier attempt along with it and shipping an empty or truncated draft
  under a hard ``FAILED`` status instead.

This module tracks the best-scoring attempt's full result snapshot across
one turn's loop, so both failure shapes resolve the same way: the turn's
final result is whichever attempt actually scored best, not merely the one
that happened to run last.
"""

from typing import Any, Optional

#: Every field a verify node's own returned update carries that fully
#: describes one attempt's outcome -- everything needed to ship that attempt
#: as the turn's final result without re-running anything. Shared between
#: draft_graph.DraftState and revise_graph.ReviseState, which both use this
#: exact field set for their own verify-node updates (revise_graph has no
#: ``reasoning_level``/``company_adapter``/``company_rules`` in its own
#: update, so those are simply absent from the snapshot there -- see
#: ``snapshot_attempt``'s own ``if field in update`` filter).
ATTEMPT_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "draft",
    "confidence_score",
    "combined_score",
    "requires_human_approval",
    "requires_revision",
    "evaluation_notes",
    "verification",
    "judge",
    "judge_available",
    "repair_items",
    "missing_information",
    "applied_rules",
    "status",
    "pii_findings",
)


def snapshot_attempt(update: dict[str, Any], draft_text: str) -> dict[str, Any]:
    """Extract one attempt's full-result snapshot from a verify node's update.

    Args:
        update: The dict a verify node is about to return.
        draft_text: This attempt's normalized draft text -- passed
            separately rather than read from ``update`` since callers
            sometimes finish building ``update["draft"]`` after this is
            computed.

    Returns:
        The snapshot, suitable for ``best_of`` and for splicing straight
        back into a future ``update`` dict via ``dict.update``.
    """
    snapshot = {field: update[field] for field in ATTEMPT_SNAPSHOT_FIELDS if field in update}
    snapshot["draft"] = draft_text
    return snapshot


def recover_from_failed_attempt(
    best_attempt: dict[str, Any], attempt_number: int, error_note: str
) -> dict[str, Any]:
    """Ship the best attempt seen so far instead of a blank/crashed retry pass.

    C3: before this, a repair/rewrite pass that timed out or raised
    discarded whatever a previous, already-verified attempt had produced
    and returned a hard ``FAILED`` result with an empty or truncated draft
    -- even when an earlier attempt had already produced a perfectly good,
    verified letter. There is nothing to recover on a turn's *first*
    attempt (no ``best_attempt`` exists yet, since ``verify`` hasn't run
    once) -- that path is untouched; this only changes what happens when a
    *later* repair pass is what crashed.

    Args:
        best_attempt: The snapshot from ``snapshot_attempt``/``best_of``.
        attempt_number: This (failed) attempt's own number, for the
            returned state's bookkeeping.
        error_note: A short Turkish note recorded on the result so the
            crash is still observable even though it didn't fail the turn.

    Returns:
        ``best_attempt``'s own fields plus ``attempts``/``error`` and
        ``restored_from_best_attempt: True`` -- the latter tells the
        caller's own routing function to go straight to "end": this is
        already a fully verified result, re-verifying it would be wasted
        work at best and could itself fail again at worst.
    """
    return {
        **best_attempt,
        "attempts": attempt_number,
        "error": error_note,
        "restored_from_best_attempt": True,
    }


def best_of(
    current: dict[str, Any], previous_best: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """Return whichever attempt snapshot scores higher.

    Args:
        current: This attempt's snapshot.
        previous_best: The best snapshot seen so far this turn, or ``None``
            on the first attempt.

    Returns:
        ``current`` when it scores at least as well as ``previous_best``
        (a tie favors the newer attempt -- it already incorporates every
        fix applied since, so it is the more complete result of the two),
        otherwise ``previous_best`` unchanged.
    """
    if previous_best is None:
        return current
    if current.get("combined_score", -1.0) >= previous_best.get("combined_score", -1.0):
        return current
    return previous_best
