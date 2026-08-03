"""Measures the deterministic intent gate against the intent gold set.

Binds to :func:`app.ai.workflows.planner.resolve_plan_deterministic` -- the
LLM-free half of ``resolve_plan``. Deliberately *not* the full ``resolve_plan``:
that one falls through to a fast-tier model call, which would make the run slow,
non-reproducible, and would hide the number this suite exists to produce -- how
often the deterministic layer has to escalate at all.

``resolve_plan_deterministic`` returning None is the abstention signal. It has no
notion of confidence today, so a decision is recorded at 1.0 and an abstention at
0.0. That is the honest encoding of a binary layer, and it is what makes the
expected-calibration-error figure meaningful: a layer that claims 1.0 on every
decision and is wrong on some of them has a calibration error equal to its own
error rate, which is precisely the gap a scored layer is meant to close.
"""

from typing import Any

from app.ai.workflows.planner import resolve_plan_deterministic
from evaluation.harness.runner import EvalCase, EvalRun, load_cases, run_cases
from evaluation.metrics import Prediction

SUITE = "intents"
DATASET = "intents"

#: The gold set records whether a document is attached as a boolean; the planner
#: takes the document's storage path. Any non-empty path behaves identically for
#: every branch the planner has, so one placeholder stands in for all of them.
_DOCUMENT_PLACEHOLDER = "uploads/evrak_gold.pdf"


def decide(case: EvalCase) -> dict[str, Any]:
    """Run one gold-set case through the deterministic intent gate.

    Args:
        case: The gold-set case.

    Returns:
        The observation dict: resolved intent, plan steps, the planner's own
        ``source`` label, and whether it abstained.
    """
    document_id = _DOCUMENT_PLACEHOLDER if case.payload.get("document_attached") else None

    decision = resolve_plan_deterministic(
        case.payload.get("message", ""),
        document_id,
        case.payload.get("previous_intent"),
        bool(case.payload.get("has_last_draft")),
    )

    if decision is None:
        return {"intent": None, "steps": [], "source": None, "abstained": True}

    return {
        "intent": decision.intent,
        "steps": list(decision.steps),
        "source": decision.source,
        "abstained": False,
    }


def run() -> EvalRun:
    """Run the whole intent gold set.

    Returns:
        The completed run.
    """
    return run_cases(SUITE, DATASET, load_cases(DATASET), decide)


def to_predictions(run_result: EvalRun) -> list[Prediction]:
    """Convert a run into the shape the classification metrics consume.

    A case whose gold answer is ``expected_abstain: true`` is genuinely
    ambiguous -- the right behaviour is to escalate, so abstaining on it is a
    *success*. Encoding that as expected/predicted ``"<abstain>"`` lets the same
    macro-F1 reward correct escalation instead of penalising it.

    Args:
        run_result: A completed intent run.

    Returns:
        One prediction per case.
    """
    predictions: list[Prediction] = []

    for result in run_result.results:
        wants_abstain = bool(result.case.expected.get("expected_abstain"))
        abstained = bool(result.observed.get("abstained"))

        if wants_abstain:
            predictions.append(
                Prediction(
                    expected="<abstain>",
                    predicted="<abstain>" if abstained else result.observed.get("intent"),
                    confidence=0.0 if abstained else 1.0,
                    abstained=False,
                )
            )
            continue

        predictions.append(
            Prediction(
                expected=str(result.case.expected.get("intent")),
                predicted=None if abstained else result.observed.get("intent"),
                confidence=0.0 if abstained else 1.0,
                abstained=abstained,
            )
        )

    return predictions


def failures(run_result: EvalRun) -> list[dict[str, Any]]:
    """List the cases the gate got wrong, for the report's detail section.

    Args:
        run_result: A completed intent run.

    Returns:
        One row per failing case, with enough context to act on it.
    """
    rows: list[dict[str, Any]] = []

    for result in run_result.results:
        expected_intent = result.case.expected.get("intent")
        wants_abstain = bool(result.case.expected.get("expected_abstain"))
        abstained = bool(result.observed.get("abstained"))
        observed_intent = result.observed.get("intent")

        if wants_abstain:
            failed = not abstained
        else:
            failed = abstained or observed_intent != expected_intent

        if not failed:
            continue

        rows.append(
            {
                "id": result.case.id,
                "category": result.case.category,
                "message": result.case.payload.get("message", ""),
                "document_attached": bool(result.case.payload.get("document_attached")),
                "previous_intent": result.case.payload.get("previous_intent"),
                "expected": "<abstain>" if wants_abstain else expected_intent,
                "observed": "<abstain>" if abstained else observed_intent,
                "source": result.observed.get("source"),
            }
        )

    return rows
