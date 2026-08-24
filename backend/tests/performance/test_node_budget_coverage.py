"""Guards against a dead entry in BudgetPolicy.node_seconds.

``BudgetPolicy.node_seconds``'s own docstring states the invariant this file
enforces: "Every key must be consumed by a node somewhere; a dead entry is a
budget someone believes is enforced and is not." Nothing checked that claim
until now -- a key could be renamed, removed from a node's actual
``node_timeout("...")``/``node_budget("...", ...)`` call, and the policy
would keep shipping a budget for a node that no longer reads it, silently.

A static source scan, not a graph execution: cheap, deterministic, and
exactly matches what the invariant is actually about -- whether the budget
key string appears as an argument to one of the two functions that ever
read ``BudgetPolicy.node_seconds`` by key
(``app.ai.workflows.resilience.node_timeout``'s decorator argument, or a
direct ``app.ai.policy.budget.node_budget(...)`` call), not whether the node
ever actually ran during this test.
"""

import re
from pathlib import Path

from app.ai.policy import get_policy

#: tests/performance/test_node_budget_coverage.py -> tests/performance ->
#: tests -> /workspace (container-relative, same convention as
#: test_budget_export_freshness.py's identical comment).
WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "app" / "ai" / "workflows"

#: Matches `node_timeout("name")` and `node_budget("name", ...)` /
#: `node_budget("name")` call-site literals across every workflow module --
#: the only two functions that ever read `BudgetPolicy.node_seconds` by key
#: (see app/ai/policy/budget.py::node_budget and app/ai/workflows/
#: resilience.py::node_timeout).
_BUDGET_KEY_PATTERN = re.compile(r'node_(?:timeout|budget)\(\s*"([^"]+)"')


def _budget_keys_referenced_in_source() -> set[str]:
    referenced: set[str] = set()
    for path in WORKFLOWS_DIR.glob("*.py"):
        referenced.update(_BUDGET_KEY_PATTERN.findall(path.read_text(encoding="utf-8")))
    return referenced


def test_every_node_seconds_key_is_consumed_by_a_node() -> None:
    node_seconds_keys = set(get_policy().budget.node_seconds)
    referenced = _budget_keys_referenced_in_source()

    dead_entries = node_seconds_keys - referenced
    assert not dead_entries, (
        f"BudgetPolicy.node_seconds has entr{'y' if len(dead_entries) == 1 else 'ies'} "
        f"no node reads: {sorted(dead_entries)}. Either wire it into a real "
        "node_timeout(...)/node_budget(...) call, or remove it -- see that "
        "field's own docstring on why a dead entry is worse than none."
    )


def test_the_scan_itself_actually_finds_known_budget_keys() -> None:
    """A regression guard on the regex/glob above, not on the policy.

    If this ever starts failing while the one above keeps passing, the scan
    silently stopped finding anything (an emptied glob, a moved directory) --
    which would make the real test above vacuously pass no matter what
    `node_seconds` actually contains.
    """
    referenced = _budget_keys_referenced_in_source()
    assert {"analyze", "route", "writer"}.issubset(referenced)
