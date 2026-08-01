"""Unit tests for planning_graph's dependency-skip guard (D6).

Without this, a step whose dependency failed still ran on empty/garbage
input -- a failed draft (draft="") still let routing run and land on
"human approval needed", an outcome visually indistinguishable from a real
routing decision. ``_dependency_failed`` is what ``execute_step_node``
consults before dispatching a step at all.
"""

from app.ai.workflows.planning_graph import _STEP_DEPENDENCIES, _append_history, _dependency_failed


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
    assert _dependency_failed("chat", {}, {}) is None


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


def test_step_dependency_table_only_covers_the_two_declared_edges():
    assert _STEP_DEPENDENCIES == {"draft": ("classification",), "routing": ("draft",)}


# ==========================================
# History reducer
# ==========================================
def test_append_history_concatenates_and_trims_to_the_window():
    from app.ai.workflows.planning_graph import HISTORY_WINDOW

    left = [{"role": "user", "content": f"msg{i}"} for i in range(HISTORY_WINDOW)]
    right = [{"role": "assistant", "content": "reply"}]

    result = _append_history(left, right)

    assert len(result) == HISTORY_WINDOW
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
