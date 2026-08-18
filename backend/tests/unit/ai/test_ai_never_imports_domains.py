"""Static enforcement of the repo's central layering rule (see
`docs/architecture/backend.md`, `app.ai.workflows.routing_graph`'s own
module docstring): `app.ai.*` never imports `app.domains.*` directly.

Faz 4 (#201) is the phase most tempted to break this -- the transfer flow
needs `app.domains.transfers`, `app.domains.drafts`, `app.domains.users` for
real DB reads. All of it goes through `transfer_provider`
(`app.domains.transfers.provider.TransferGraphProvider`), injected into
`create_planning_graph` the same way `units_provider`/`adapter_provider`
already are -- never imported into `app/ai/**` directly. This also protects
the *other* half of the same invariant: human chat messages
(`app.domains.messaging`) must never be readable from inside the planning
graph at all, since that is what makes prompt injection via a colleague's
DM structurally impossible (see the plan's §H) -- an `app.domains.messaging`
import anywhere under `app/ai` would be exactly the crack that opens.

AST-based (not a runtime import check): a lazily-imported violation inside a
function body would otherwise only surface the first time that branch
actually executes, which a mocked-out unit test suite might never trigger.
"""

import ast
from pathlib import Path

AI_ROOT = Path(__file__).resolve().parents[3] / "app" / "ai"


def _imports_domains(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits.extend(alias.name for alias in node.names if alias.name.startswith("app.domains"))
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.domains"):
            hits.append(node.module)
    return hits


def test_no_module_under_app_ai_imports_app_domains():
    violations = {}
    for path in AI_ROOT.rglob("*.py"):
        hits = _imports_domains(path)
        if hits:
            violations[str(path.relative_to(AI_ROOT.parents[1]))] = hits
    assert not violations, (
        "app.ai.* must never import app.domains.* directly -- inject a plain "
        f"callable/provider object instead (see units_provider/adapter_provider/"
        f"transfer_provider). Violations: {violations}"
    )
