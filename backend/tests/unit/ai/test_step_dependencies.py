"""Unit tests for planning_graph's dependency-skip guard (D6).

Without this, a step whose dependency failed still ran on empty/garbage
input -- a failed draft (draft="") still let routing run and land on
"human approval needed", an outcome visually indistinguishable from a real
routing decision. ``_dependency_failed`` is what ``execute_step_node``
consults before dispatching a step at all.
"""

from app.ai.workflows.planning_graph import (
    _append_history,
    _dependency_failed,
    _pending_consolidation,
)
from app.ai.workflows.step_graph import STEP_SPECS


def test_draft_depends_on_a_successful_classification():
    state = {"classification_result": {"status": "FAILED"}}
    assert _dependency_failed("draft", state, {}) == "classification"


def test_routing_depends_on_a_successful_draft():
    state = {"draft_result": {"status": "FAILED"}}
    assert _dependency_failed("routing", state, {}) == "draft"


def test_no_dependency_failure_when_dependency_succeeded():
    state = {"classification_result": {"status": "COMPLETED"}}
    assert _dependency_failed("draft", state, {}) is None


def test_no_dependency_failure_when_dependency_has_not_run_yet():
    """A step with no _STEP_DEPENDENCIES entry, or whose dependency simply
    has no result yet, must not be blocked."""
    assert _dependency_failed("draft", {}, {}) is None
    assert _dependency_failed("classification", {"draft_result": {"status": "FAILED"}}, {}) is None
    assert _dependency_failed("assist", {}, {}) is None


def test_a_dependency_that_ran_earlier_this_same_superstep_is_visible_via_updates():
    """A dependency step that just completed this turn is not yet folded into
    `state` -- execute_step_node passes it via `updates` instead."""
    updates = {"classification_result": {"status": "FAILED"}}
    assert _dependency_failed("draft", {}, updates) == "classification"


def test_updates_take_precedence_over_a_stale_state_result():
    state = {"classification_result": {"status": "COMPLETED"}}
    updates = {"classification_result": {"status": "FAILED"}}
    assert _dependency_failed("draft", state, updates) == "classification"


def test_routing_is_unaffected_by_a_failed_classification_it_does_not_depend_on():
    """routing's only declared dependency is draft, not classification --
    a failed classification must not block it directly (draft's own guard
    already covers the transitive case)."""
    state = {"classification_result": {"status": "FAILED"}, "draft_result": {"status": "COMPLETED"}}
    assert _dependency_failed("routing", state, {}) is None


def test_step_specs_cover_all_dispatchable_steps_with_expected_edges():
    assert set(STEP_SPECS) == {
        "classification", "brief", "draft", "routing", "assist", "revise", "clarify", "refuse",
        "transfer_execute",
    }
    assert STEP_SPECS["brief"].depends_on == ("classification",)
    assert STEP_SPECS["draft"].depends_on == ("classification", "brief")
    assert STEP_SPECS["routing"].depends_on == ("draft",)
    # transfer_execute declares no dependency -- it is only ever appended to
    # plan_steps once a transfer_resolve_result already exists (see
    # planning_graph._step_assist), never dispatched any other way.
    assert STEP_SPECS["transfer_execute"].depends_on == ()
    for name in ("classification", "assist", "revise", "clarify", "refuse", "transfer_execute"):
        assert STEP_SPECS[name].depends_on == ()


def test_routing_is_skipped_when_draft_declined_to_run():
    """draft can settle SKIPPED (not FAILED) when
    app.ai.workflows.relevance refuses an off-topic request -- routing must
    not run on the resulting empty draft either, the same as it wouldn't on
    a genuine failure."""
    state = {"draft_result": {"status": "SKIPPED", "reason": "unrelated"}}
    assert _dependency_failed("routing", state, {}) == "draft"


# ==========================================
# History reducer
# ==========================================
def test_append_history_concatenates_and_trims_to_the_raw_cap():
    from app.ai.workflows.planning_graph import HISTORY_RAW_CAP

    left = [{"role": "user", "content": f"msg{i}"} for i in range(HISTORY_RAW_CAP)]
    right = [{"role": "assistant", "content": "reply"}]

    result = _append_history(left, right)

    assert len(result) == HISTORY_RAW_CAP
    assert result[-1] == {"role": "assistant", "content": "reply"}
    assert result[0] == {"role": "user", "content": "msg1"}


def test_append_history_tolerates_none_on_either_side():
    assert _append_history(None, [{"role": "user", "content": "hi"}]) == [
        {"role": "user", "content": "hi"}
    ]
    assert _append_history([{"role": "user", "content": "hi"}], None) == [
        {"role": "user", "content": "hi"}
    ]
    assert _append_history(None, None) == []


# ==========================================
# Memory consolidation trigger (_pending_consolidation)
# ==========================================
def _turns(n: int) -> list[dict[str, str]]:
    return [{"role": "user", "content": f"msg{i}"} for i in range(n)]


def test_pending_consolidation_is_empty_when_history_fits_the_window():
    pending, boundary = _pending_consolidation(_turns(10), 0, window=12, batch_size=4)
    assert pending == []
    assert boundary == 0


def test_pending_consolidation_is_empty_below_the_batch_size():
    # 14 turns, window=12 -> 2 overflowed, batch_size=4 -> not worth a call yet.
    pending, boundary = _pending_consolidation(_turns(14), 0, window=12, batch_size=4)
    assert pending == []
    assert boundary == 0


def test_pending_consolidation_fires_at_the_batch_size():
    # 16 turns, window=12 -> 4 overflowed, meets batch_size=4.
    history = _turns(16)
    pending, boundary = _pending_consolidation(history, 0, window=12, batch_size=4)
    assert pending == history[0:4]
    assert boundary == 4


def test_pending_consolidation_only_returns_the_newly_overflowed_delta():
    # Already summarized through 4; 20 turns -> boundary at 8 -> 4 new pending.
    history = _turns(20)
    pending, boundary = _pending_consolidation(history, 4, window=12, batch_size=4)
    assert pending == history[4:8]
    assert boundary == 8


def test_pending_consolidation_tolerates_empty_history():
    pending, boundary = _pending_consolidation([], 0, window=12, batch_size=4)
    assert pending == []
    assert boundary == 0
