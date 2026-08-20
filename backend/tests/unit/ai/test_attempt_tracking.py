"""Unit tests for app.ai.workflows.attempt_tracking -- the shared "best
attempt wins" bookkeeping both draft_graph and revise_graph's repair loops
use (C2/C3)."""

from app.ai.workflows.attempt_tracking import (
    best_of,
    recover_from_failed_attempt,
    snapshot_attempt,
)


def test_snapshot_attempt_pulls_only_the_known_fields_plus_the_given_draft():
    update = {
        "draft": "stale text a caller might overwrite later",
        "combined_score": 92.0,
        "status": "NEEDS_HUMAN_APPROVAL",
        "some_unrelated_field": "ignored",
    }

    snapshot = snapshot_attempt(update, "the actual normalized draft text")

    assert snapshot["draft"] == "the actual normalized draft text"
    assert snapshot["combined_score"] == 92.0
    assert snapshot["status"] == "NEEDS_HUMAN_APPROVAL"
    assert "some_unrelated_field" not in snapshot


def test_snapshot_attempt_tolerates_missing_optional_fields():
    snapshot = snapshot_attempt({"combined_score": 50.0}, "draft text")
    assert snapshot == {"combined_score": 50.0, "draft": "draft text"}


def test_best_of_returns_current_on_the_first_attempt():
    current = {"combined_score": 42.0}
    assert best_of(current, None) is current


def test_best_of_keeps_the_higher_scoring_snapshot():
    first = {"combined_score": 92.0}
    second = {"combined_score": 70.0}
    assert best_of(second, first) is first


def test_best_of_prefers_the_newer_attempt_on_a_tie():
    first = {"combined_score": 80.0}
    second = {"combined_score": 80.0}
    assert best_of(second, first) is second


def test_best_of_switches_to_a_strictly_better_later_attempt():
    first = {"combined_score": 60.0}
    second = {"combined_score": 95.0}
    assert best_of(second, first) is second


def test_recover_from_failed_attempt_carries_the_snapshots_own_fields_forward():
    best = {"draft": "the good draft", "combined_score": 92.0, "status": "NEEDS_HUMAN_APPROVAL"}

    recovered = recover_from_failed_attempt(best, attempt_number=2, error_note="onarım çöktü")

    assert recovered["draft"] == "the good draft"
    assert recovered["combined_score"] == 92.0
    assert recovered["status"] == "NEEDS_HUMAN_APPROVAL"
    assert recovered["attempts"] == 2
    assert recovered["error"] == "onarım çöktü"
    assert recovered["restored_from_best_attempt"] is True
