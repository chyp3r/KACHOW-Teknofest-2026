"""Measures the deterministic draft gate against the draft gold set.

Binds to :func:`app.ai.verification.draft_verifier.verify_draft`. The judge
(``llm_judge.judge_draft``) is deliberately excluded: it is a model call, so
including it would make the run slow and non-reproducible, and the number this
suite exists to produce is about the *deterministic* half specifically.

The headline metric is the **false-positive rate** -- correctly grounded drafts
that the gate nonetheless sends to a human. That number is not an abstraction:
`draft_graph.py` turns `requires_human_approval` into a HITL interrupt, so every
false positive is a real interruption a correct draft did not need. The gold set
carries paraphrased-but-grounded drafts specifically to measure it, because
`_is_supported` compares by folded substring and falls back to a fixed 0.75 token
overlap, and legitimate rewording is exactly what that misses.
"""

from typing import Any

from app.ai.verification.draft_verifier import verify_draft
from evaluation.harness.runner import EvalCase, EvalRun, load_cases, run_cases
from evaluation.metrics import BinaryRates, binary_rates

SUITE = "drafts"
DATASET = "drafts"


def decide(case: EvalCase) -> dict[str, Any]:
    """Run one gold-set draft through the deterministic verifier.

    Args:
        case: The gold-set case.

    Returns:
        The observation dict: the approval decision, the score, and the claims
        and structural gaps that produced them.
    """
    report = verify_draft(
        case.payload.get("draft", ""),
        source_document=case.payload.get("source_document", ""),
        context=case.payload.get("context", ""),
        classification=case.payload.get("classification") or {},
        instructions=case.payload.get("instructions", ""),
        strict=bool(case.payload.get("strict", True)),
    )

    return {
        "requires_human_approval": report.requires_human_approval,
        "confidence_score": report.confidence_score,
        "unsupported_claims": [
            {"kind": claim.kind, "value": claim.value}
            for claim in report.unsupported_claims
        ],
        "unsupported_claim_count": len(report.unsupported_claims),
        "missing_structure": list(report.missing_structure),
        "placeholder_count": report.placeholder_count,
    }


def run() -> EvalRun:
    """Run the whole draft gold set.

    Returns:
        The completed run.
    """
    return run_cases(SUITE, DATASET, load_cases(DATASET), decide)


def to_rates(run_result: EvalRun) -> BinaryRates:
    """Tally the approval decision against the gold answer.

    Args:
        run_result: A completed draft run.

    Returns:
        The binary confusion counts for ``requires_human_approval``.
    """
    return binary_rates(
        [
            (
                bool(result.case.expected.get("requires_human_approval")),
                bool(result.observed.get("requires_human_approval")),
            )
            for result in run_result.results
        ]
    )


def failures(run_result: EvalRun) -> list[dict[str, Any]]:
    """List drafts the gate judged wrongly, worst class first.

    False positives are listed before false negatives because they are the
    class this gate is currently expected to fail on, and because each one is a
    user-visible interruption rather than a silent risk.

    Args:
        run_result: A completed draft run.

    Returns:
        One row per failing case.
    """
    rows: list[dict[str, Any]] = []

    for result in run_result.results:
        expected = bool(result.case.expected.get("requires_human_approval"))
        observed = bool(result.observed.get("requires_human_approval"))
        if expected == observed:
            continue

        rows.append(
            {
                "id": result.case.id,
                "category": result.case.category,
                "kind": "false_positive" if observed else "false_negative",
                "expected_requires_human_approval": expected,
                "observed_requires_human_approval": observed,
                "confidence_score": result.observed.get("confidence_score"),
                "unsupported_claims": result.observed.get("unsupported_claims"),
                "missing_structure": result.observed.get("missing_structure"),
                "placeholder_count": result.observed.get("placeholder_count"),
            }
        )

    rows.sort(key=lambda row: 0 if row["kind"] == "false_positive" else 1)
    return rows


def claim_detection_gaps(run_result: EvalRun) -> list[dict[str, Any]]:
    """Compare detected unsupported-claim counts against the gold count.

    Separate from :func:`failures` on purpose: a draft can land on the right
    approval decision for the wrong reason -- flagged for a missing signature
    block while the fabricated document number went unnoticed -- and only this
    view shows it.

    Args:
        run_result: A completed draft run.

    Returns:
        One row per case whose detected claim count differs from the gold count.
    """
    rows: list[dict[str, Any]] = []

    for result in run_result.results:
        expected_count = result.case.expected.get("unsupported_claim_count")
        if expected_count is None:
            continue

        observed_count = result.observed.get("unsupported_claim_count", 0)
        if int(expected_count) == int(observed_count):
            continue

        rows.append(
            {
                "id": result.case.id,
                "category": result.case.category,
                "expected_claim_count": int(expected_count),
                "observed_claim_count": int(observed_count),
                "observed_claims": result.observed.get("unsupported_claims"),
            }
        )

    return rows
