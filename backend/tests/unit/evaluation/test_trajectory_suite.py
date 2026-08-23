"""Guards the trajectory suite's two riskiest pieces: the sequence-scoring
metrics (a silent bug here would let a real regression -- a node dropped or
looped -- read as a passing run) and the end-to-end wiring against the real
compiled planning graph (proof `make eval --suite trajectories` actually
measures something, not just that the scoring math is self-consistent).
"""

import pytest

from evaluation.harness.runner import CaseResult, EvalCase, EvalRun
from evaluation.harness.trajectory_suite import (
    _levenshtein_over_tokens,
    decide,
    failures,
    sequence_summary,
)


def _case(case_id: str, expected_sequence: list, expected_paused_at=None) -> EvalCase:
    return EvalCase(
        id=case_id,
        category="test",
        payload={"message": "irrelevant"},
        expected={"node_sequence": expected_sequence, "paused_at": expected_paused_at},
    )


def _result(case: EvalCase, observed_sequence: list, observed_paused_at=None) -> CaseResult:
    return CaseResult(
        case=case,
        observed={"node_sequence": observed_sequence, "paused_at": observed_paused_at},
        duration_ms=0.0,
    )


# ==========================================
# Edit distance over node-name tokens
# ==========================================


def test_levenshtein_zero_for_identical_sequences():
    seq = ["planning", "executor", "focus", "consolidate_memory"]
    assert _levenshtein_over_tokens(seq, seq) == 0


def test_levenshtein_counts_one_extra_executor_loop_as_one_edit():
    expected = ["planning", "executor", "focus", "consolidate_memory"]
    observed = ["planning", "executor", "executor", "focus", "consolidate_memory"]
    assert _levenshtein_over_tokens(observed, expected) == 1


def test_levenshtein_treats_same_length_different_nodes_as_one_edit_per_slot():
    # A same-length sequence that differs at every position -- proves the
    # tokenizer maps each *distinct* node name to its own code point rather
    # than, say, comparing sequences character-by-character on their
    # to-string() representation (which would give a wildly different,
    # meaningless number here).
    assert _levenshtein_over_tokens(["a", "b", "c"], ["x", "y", "z"]) == 3


# ==========================================
# sequence_summary / failures
# ==========================================


def test_sequence_summary_all_exact_matches():
    case1 = _case("t1", ["planning", "executor", "focus", "consolidate_memory"])
    case2 = _case("t2", ["planning", "executor", "focus", "consolidate_memory"])
    run = EvalRun(
        suite="trajectories",
        dataset="trajectories",
        results=[_result(case1, case1.expected["node_sequence"]), _result(case2, case2.expected["node_sequence"])],
    )

    summary = sequence_summary(run)

    assert summary["cases"] == 2
    assert summary["exact_match_rate"] == 1.0
    assert summary["mean_edit_distance"] == 0.0
    assert summary["unexpected_node_rate"] == 0.0
    assert summary["paused_at_mismatches"] == []
    assert failures(run) == []


def test_sequence_summary_flags_a_node_the_graph_should_never_have_visited():
    """The regression this suite exists to catch: for a fixed input, a node
    outside the gold set's own expected set fires (e.g. a gate that should
    have been skipped ran anyway) -- unexpected_node_rate must be > 0 even
    though the sequence otherwise looks broadly plan-shaped."""
    case = _case("t1", ["planning", "executor", "focus", "consolidate_memory"])
    observed = ["planning", "executor", "human_gate", "focus", "consolidate_memory"]
    run = EvalRun(suite="trajectories", dataset="trajectories", results=[_result(case, observed)])

    summary = sequence_summary(run)

    assert summary["exact_match_rate"] == 0.0
    assert summary["mean_edit_distance"] == 1
    # 1 of the 5 observed node-visits ("human_gate") is not in the expected set.
    assert summary["unexpected_node_rate"] == pytest.approx(1 / 5)

    rows = failures(run)
    assert len(rows) == 1
    assert rows[0]["id"] == "t1"
    assert rows[0]["edit_distance"] == 1


def test_sequence_summary_reports_paused_at_mismatch():
    case = _case("t1", ["planning", "executor", "__interrupt__"], expected_paused_at="human_gate")
    run = EvalRun(
        suite="trajectories",
        dataset="trajectories",
        results=[_result(case, case.expected["node_sequence"], observed_paused_at="brief_gate")],
    )

    summary = sequence_summary(run)

    # The sequence itself matched exactly (both end in __interrupt__) --
    # only the *which node it paused at* signal catches this failure class.
    assert summary["exact_match_rate"] == 1.0
    assert summary["paused_at_mismatches"] == [
        {"id": "t1", "expected": "human_gate", "observed": "brief_gate"}
    ]


def test_sequence_summary_empty_run_does_not_divide_by_zero():
    run = EvalRun(suite="trajectories", dataset="trajectories", results=[])
    summary = sequence_summary(run)
    assert summary["cases"] == 0
    assert summary["exact_match_rate"] == 0.0
    assert summary["mean_edit_distance"] == 0.0
    assert summary["unexpected_node_rate"] == 0.0


# ==========================================
# End-to-end: the real compiled planning graph
# ==========================================


def test_decide_a_plain_chat_message_never_touches_a_gate(monkeypatch):
    from app.core.config import settings

    # decide() alone (unlike run()) does not disable the pre-draft brief
    # gate itself -- irrelevant for this assist-only case (assist never
    # produces plan_steps that touch "brief"), but set for parity with the
    # draft probe below and so this file never depends on suite ordering.
    monkeypatch.setattr(settings, "HITL_BRIEF_GATE_ENABLED", False)
    case = EvalCase(
        id="chat-probe",
        category="sohbet",
        payload={"message": "Merhaba"},
        expected={
            "node_sequence": ["planning", "executor", "focus", "consolidate_memory"],
            "paused_at": None,
        },
    )

    observed = decide(case)

    assert observed["node_sequence"] == ["planning", "executor", "focus", "consolidate_memory"]
    assert observed["paused_at"] is None


def test_decide_a_needs_input_draft_pauses_at_human_gate(monkeypatch):
    from app.core.config import settings

    # Every gold case's classification stub has empty `fields`, which would
    # otherwise always open the pre-draft brief_gate first (see
    # `trajectory_suite.run`'s own docstring) -- disabled here so this test
    # exercises the gate it's actually named for.
    monkeypatch.setattr(settings, "HITL_BRIEF_GATE_ENABLED", False)
    case = EvalCase(
        id="draft-probe",
        category="taslak_dusuk_guven_onay",
        payload={
            "message": "Bu konuda bir bilgilendirme metni hazırlamanı istiyorum.",
            "draft_result": {
                "status": "NEEDS_INPUT",
                "draft": "Sayın [MUHATAP],\n\nArz ederim.",
                "confidence_score": 40.0,
                "combined_score": 40.0,
                "requires_human_approval": True,
                "missing_information": [
                    {"key": "muhatap", "label": "MUHATAP", "why": "", "example": None, "required": True}
                ],
                "verification": {},
                "judge": {},
                "applied_rules": [],
                "source_document": "",
                "context": "",
                "classification": {},
                "instructions": "",
                "correspondence_type": "cover_letter",
            },
        },
        expected={
            "node_sequence": ["planning", "executor", "executor", "executor", "__interrupt__"],
            "paused_at": "human_gate",
        },
    )

    observed = decide(case)

    assert observed["node_sequence"][-1] == "__interrupt__"
    assert observed["node_sequence"].count("executor") == 3
    assert observed["paused_at"] == "human_gate"


def test_run_the_whole_gold_set_is_fully_offline_and_all_exact_match():
    """The suite's own committed gold set (`evaluation/datasets/
    trajectories.jsonl`), run for real -- proof the dataset and the harness
    still agree with each other, the same guarantee `make eval --suite
    trajectories` depends on."""
    from evaluation.harness.trajectory_suite import run as run_trajectories

    result = run_trajectories()

    summary = sequence_summary(result)
    assert summary["cases"] >= 6
    assert summary["exact_match_rate"] == 1.0
