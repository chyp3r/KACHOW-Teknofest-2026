"""Resolves a node's time budget for the reasoning level of the run in progress.

``reasoning_levels.py`` has carried a ``timeout_multiplier`` since the feature
landed (0.6 fast, 1.0 balanced, 1.8 deep), but it only ever reached the
*service* layer's outer timeout. Node budgets stayed fixed, so a ``deep`` run
was given 1.8x the wall clock overall while every individual node kept its
balanced ceiling -- the extra budget could not actually be spent where the extra
work happens.

Resolution is per call rather than per graph build. ``@node_timeout`` used to
take a float, which meant the budget was baked in when the graph was compiled;
a graph is compiled once per process, so no per-request value could ever reach
it. Taking a node *name* and resolving at call time is what makes the multiplier
usable at all.
"""

from app.ai.policy import get_policy
from app.ai.reasoning_levels import get_reasoning_level_preset
from app.core.enums.reasoning_level import ReasoningLevel

__all__ = ["node_budget"]


def node_budget(node: str, level: "ReasoningLevel | str | None" = None) -> float:
    """Resolve the timeout budget for one node at one reasoning level.

    Args:
        node: The node's name, as keyed in ``BudgetPolicy.node_seconds``.
        level: The run's reasoning level. Unknown, missing or malformed values
            resolve to balanced -- this is read from checkpointed graph state
            and must never raise on a value written by an older version.

    Returns:
        The budget in seconds, scaled by the level's multiplier and clamped to
        the whole-workflow ceiling. A node with no configured budget falls back
        to the ceiling, which is a no-op timeout rather than an accidental
        zero-second one.
    """
    policy = get_policy().budget
    base = policy.node_seconds.get(node)
    if base is None:
        return policy.workflow_ceiling_seconds

    scaled = base * get_reasoning_level_preset(level).timeout_multiplier
    return min(scaled, policy.workflow_ceiling_seconds)
