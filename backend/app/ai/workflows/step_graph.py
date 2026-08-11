"""Declarative step dependencies and readiness computation for the executor.

Generalises the old `_STEP_DEPENDENCIES` (a 2-entry dict covering only
`draft`/`routing`, consulted only to decide skip-vs-run) into a catalog
spanning every dispatchable step name, and replaces `current_step_idx`-based
array indexing with a readiness computation over `state`. This is the
foundation a dynamic executor needs -- even though every plan
`PLAN_BY_INTENT` produces today is a strict linear chain and never actually
exercises the difference between "next by position" and "next by readiness".
"""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class StepSpec:
    """One dispatchable step's scheduling metadata.

    Attributes:
        name: The step name, matching a `STEP_RUNNERS` key in
            `planning_graph.py`.
        depends_on: Other step names that must have run -- with any outcome,
            success, failure, or skip -- before this one is eligible. Only
            dependencies that are *also* part of the current turn's plan
            apply: `assist`'s plan never includes `classification`, so
            `rag`'s declared dependency on it is a no-op there.
        parallel_safe: Whether this step may run concurrently with another
            `parallel_safe` step that is also ready in the same turn. No
            step is `True` today -- see `ready_steps`'s docstring for why.
    """

    name: str
    depends_on: tuple[str, ...] = ()
    parallel_safe: bool = False


#: One entry per name `STEP_RUNNERS` can dispatch, and per name any
#: `PLAN_BY_INTENT` combination can actually produce. A standalone `rag` step
#: used to be declared here too, but no plan ever included it -- the
#: classification sub-graph already retrieves legislation for the document,
#: and the `assist` step's `search_legislation` tool covers the rest -- so it
#: was dead weight kept "for consistency" that never dispatched. Removed
#: rather than left in: an unreachable `STEP_SPECS` entry is exactly the kind
#: of state that silently drifts from what `PLAN_BY_INTENT` can produce.
STEP_SPECS: dict[str, StepSpec] = {
    "classification": StepSpec(name="classification"),
    #: Deterministic, LLM-free -- see app.ai.workflows.writing_brief. Runs
    #: after classification so a document-reply turn's role-inversion rule
    #: has fields.gonderen_kurum/muhatap to resolve against.
    "brief": StepSpec(name="brief", depends_on=("classification",)),
    "draft": StepSpec(name="draft", depends_on=("classification", "brief")),
    "routing": StepSpec(name="routing", depends_on=("draft",)),
    "assist": StepSpec(name="assist"),
    #: No dependency on "classification": revise operates on
    #: SessionFocus.active_draft, never re-classifies. See app.ai.workflows.revise.
    "revise": StepSpec(name="revise"),
    #: Deterministic, LLM-free -- see planner._build_clarify_decision.
    "clarify": StepSpec(name="clarify"),
    #: Also deterministic and LLM-free: it renders
    #: `app.ai.workflows.scope.CAPABILITY_MANIFEST` and ends the turn. It is
    #: always the only step in its plan, so it has nothing to depend on.
    "refuse": StepSpec(name="refuse"),
}


def _has_run(state: Mapping[str, Any], name: str) -> bool:
    """Whether `name`'s result is non-empty in `state`.

    `planning_node` resets every `<step>_result` field to `{}` at the start
    of a turn rather than deleting the key, so key presence alone can't tell
    a step that hasn't run yet from one that has this turn -- truthiness
    can, and is the same check `_dependency_failed`'s callers already rely
    on for the same reason.
    """
    return bool(state.get(f"{name}_result"))


def ready_steps(
    plan_steps: list[str],
    state: Mapping[str, Any],
    specs: Mapping[str, StepSpec] = STEP_SPECS,
) -> list[str]:
    """Steps in `plan_steps` that have not run yet and are eligible to.

    Eligibility only means "this step's in-plan dependencies have run, with
    *any* outcome" -- it deliberately does not check whether a dependency
    *succeeded*. Whether a dependency's failure should skip its dependent is
    `_dependency_failed`'s job in `planning_graph.py`, evaluated separately
    once a step is chosen from this list. Splitting the two concerns keeps
    this function a pure scheduling question.

    No `StepSpec` is `parallel_safe=True` today, because every dispatchable
    step touches an LLM call at some point (even `classification` runs a
    tiered model call) -- running two of them concurrently on a single local
    Ollama instance does not shorten wall-clock time, it splits the same
    GPU/CPU between them. The flag and the multi-ready path built on top of
    it exist for a future step that is genuinely I/O-only (a cache read, a
    deterministic check), not for anything in `PLAN_BY_INTENT` as it stands.

    Args:
        plan_steps: The turn's resolved plan, in the order `planner.py`
            produced it.
        state: The graph state as of the start of this superstep.
        specs: The catalog to schedule against. Defaults to the real
            `STEP_SPECS`; overridable so a test can exercise the
            multi-`parallel_safe` branch without a real step type for it.

    Returns:
        Ready step names, in `plan_steps` order (stable). With no
        `parallel_safe` step ready alongside another today, the executor
        always takes just the first one, reproducing the old strictly
        positional order exactly.
    """
    ready = []
    for name in plan_steps:
        if _has_run(state, name):
            continue
        spec = specs.get(name, StepSpec(name=name))
        deps_in_plan = [dep for dep in spec.depends_on if dep in plan_steps]
        if any(not _has_run(state, dep) for dep in deps_in_plan):
            continue
        ready.append(name)
    return ready


def all_steps_settled(plan_steps: list[str], state: Mapping[str, Any]) -> bool:
    """Whether every step in `plan_steps` has produced a result this turn.

    Replaces the old `current_step_idx >= len(plan_steps)` termination check
    now that stepping is readiness-driven rather than positional.
    """
    return all(_has_run(state, name) for name in plan_steps)
