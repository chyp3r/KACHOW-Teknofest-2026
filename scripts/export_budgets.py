"""Exports the live BudgetPolicy to perf/k6/lib/budgets.json.

Run after changing any ``BudgetPolicy`` value in ``app/ai/policy/schema.py``:

    docker compose run --rm --no-deps backend python scripts/export_budgets.py

k6 (Workstream E2) never imports Python -- it is a standalone JS runtime, by
design (see ``perf/k6/README.md``: one load-testing tool, not two). This is
the one mechanical link between the two: the committed JSON this script
writes is what ``perf/k6/lib/thresholds.js`` reads its LLM-endpoint
threshold from, so a policy change and the k6 threshold it should move
cannot silently drift apart -- ``backend/tests/unit/ai/policy/
test_budget_export_freshness.py`` fails the moment they do.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.policy import get_policy  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
BUDGETS_PATH = REPO_ROOT / "perf" / "k6" / "lib" / "budgets.json"


def export_budgets() -> dict:
    """Build the exported payload from the live policy. Pure; no I/O."""
    budget = get_policy().budget
    return {
        "workflow_ceiling_seconds": budget.workflow_ceiling_seconds,
        "node_seconds": dict(budget.node_seconds),
    }


def main() -> None:
    payload = export_budgets()
    BUDGETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    BUDGETS_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {BUDGETS_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
