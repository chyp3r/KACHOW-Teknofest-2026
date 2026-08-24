"""Guards perf/k6/lib/budgets.json against drifting from the live BudgetPolicy.

Same tripwire idiom as ``test_prototype_freshness.py``: a committed export
whose staleness is otherwise silent. k6 (Workstream E2) is a standalone JS
runtime that never imports Python -- ``perf/k6/lib/thresholds.js`` reads its
LLM-endpoint threshold from this exact committed file, so a
``BudgetPolicy.node_seconds``/``workflow_ceiling_seconds`` change that
doesn't also update it would leave the k6 threshold silently testing
against a stale number forever. Unlike ``test_prototype_freshness.py``, this
one needs no Ollama call at all -- ``export_budgets()`` only reads the
already-loaded policy object -- so it costs nothing to run on every `pytest`.
"""

import json
import sys
from pathlib import Path

#: tests/unit/ai/test_budget_export_freshness.py -> tests/unit/ai -> tests/unit
#: -> tests -> /workspace. Container-relative, matching how every test here
#: actually runs (see scripts/export_budgets.py's own identical convention,
#: which assumes the same "docker compose run" invocation, never a bare
#: host `python`).
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from export_budgets import BUDGETS_PATH, export_budgets  # noqa: E402


def test_committed_budgets_json_matches_the_live_policy() -> None:
    if not BUDGETS_PATH.exists():
        raise AssertionError(
            f"{BUDGETS_PATH} is missing. Run: "
            "docker compose run --rm --no-deps backend python scripts/export_budgets.py"
        )

    committed = json.loads(BUDGETS_PATH.read_text(encoding="utf-8"))
    live = export_budgets()

    assert committed == live, (
        "perf/k6/lib/budgets.json is stale against the running BudgetPolicy -- "
        "rerun: docker compose run --rm --no-deps backend python scripts/export_budgets.py"
    )
