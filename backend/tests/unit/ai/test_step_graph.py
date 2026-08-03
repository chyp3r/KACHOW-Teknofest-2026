"""Unit tests for the readiness engine that replaced current_step_idx indexing.

`ready_steps`/`all_steps_settled` took over from `execute_step_node`'s old
`steps[idx]` array indexing. The tests below lock the two properties that
matter for that replacement to be safe: today's linear plans must still
execute in exactly the order they always have, and the parallel path -- built
for a step type nothing in `PLAN_BY_INTENT` uses yet -- must never silently
start running two LLM-touching steps at once.
"""

from app.ai.workflows.step_graph import StepSpec, STEP_SPECS, all_steps_settled, ready_steps


def test_no_step_is_marked_parallel_safe_today():
    """Every dispatchable step touches an LLM call somewhere in its own
    body (even `classification` runs a tiered model call) -- running two of
    them concurrently on one local Ollama instance splits GPU/CPU rather
    than shortening wall-clock time. If this ever flips true for a
    genuinely I/O-only step, this test is the tripwire that says so."""
    assert not any(spec.parallel_safe for spec in STEP_SPECS.values())


def test_a_fresh_linear_plan_is_ready_at_its_first_step_only():
    plan = ["classification", "draft", "routing"]
    assert ready_steps(plan, {}) == ["classification"]


def test_readiness_advances_one_step_at_a_time_through_a_linear_plan():
    plan = ["classification", "draft", "routing"]

    state = {"classification_result": {"status": "COMPLETED"}}
    assert ready_steps(plan, state) == ["draft"]

    state["draft_result"] = {"status": "COMPLETED"}
    assert ready_steps(plan, state) == ["routing"]

    state["routing_result"] = {"status": "COMPLETED"}
    assert ready_steps(plan, state) == []


def test_a_dependency_outside_the_plan_is_not_waited_on():
    """assist's plan never includes classification -- rag's declared
    dependency on it must not block anything when rag isn't in the plan
    either, and a single-step plan must be ready immediately."""
    assert ready_steps(["assist"], {}) == ["assist"]


def test_readiness_does_not_care_whether_a_dependency_succeeded():
    """Whether a *failed* dependency should skip its dependent is
    _dependency_failed's job, evaluated separately once execute_step_node
    picks a step -- ready_steps only tracks whether it ran at all."""
    plan = ["classification", "draft"]
    state = {"classification_result": {"status": "FAILED"}}
    assert ready_steps(plan, state) == ["draft"]


def test_all_steps_settled_is_false_until_every_step_has_a_result():
    plan = ["classification", "draft"]
    assert all_steps_settled(plan, {}) is False
    assert all_steps_settled(plan, {"classification_result": {"status": "COMPLETED"}}) is False

    full = {
        "classification_result": {"status": "COMPLETED"},
        "draft_result": {"status": "COMPLETED"},
    }
    assert all_steps_settled(plan, full) is True


def test_all_steps_settled_counts_a_skipped_result_as_settled():
    """A SKIPPED result is still a non-empty dict -- the plan must still be
    able to terminate when a step was skipped rather than run."""
    plan = ["classification", "draft"]
    state = {
        "classification_result": {"status": "FAILED"},
        "draft_result": {"status": "SKIPPED", "reason": "..."},
    }
    assert all_steps_settled(plan, state) is True


def test_two_parallel_safe_steps_are_both_reported_ready_together():
    """A synthetic spec table exercising the multi-ready path the real
    STEP_SPECS never does today: two independent, parallel-safe steps must
    both be reported ready together, not just the first one in plan order.
    Injected via `ready_steps`'s `specs` override since STEP_SPECS itself
    has no parallel_safe entry to test this against yet."""
    specs = {
        "a": StepSpec(name="a", parallel_safe=True),
        "b": StepSpec(name="b", parallel_safe=True),
    }
    assert ready_steps(["a", "b"], {}, specs=specs) == ["a", "b"]


def test_a_step_depending_on_an_unfinished_parallel_sibling_is_not_ready_yet():
    specs = {
        "a": StepSpec(name="a", parallel_safe=True),
        "b": StepSpec(name="b", parallel_safe=True),
        "c": StepSpec(name="c", depends_on=("a", "b")),
    }
    assert ready_steps(["a", "b", "c"], {}, specs=specs) == ["a", "b"]

    state = {"a_result": {"status": "COMPLETED"}, "b_result": {"status": "COMPLETED"}}
    assert ready_steps(["a", "b", "c"], state, specs=specs) == ["c"]
