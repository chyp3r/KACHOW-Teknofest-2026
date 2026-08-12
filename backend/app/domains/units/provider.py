"""Read-side access to active units for the routing graph.

`routing_graph.create_routing_graph` is compiled once per process (see
`app.api.dependency.get_routing_graph`), outside any request-scoped
`Depends(get_db)` -- same situation `app.domains.drafts.draft_recorder`
documents for draft writes. This opens and closes its own short-lived
session per call instead, so every routing decision reads the unit list as
it stands *right now*, not as it stood when the process started.

Kept inside `app.domains.units` rather than imported from `app.ai` directly:
`app.ai.workflows.routing_graph` never imports `app.domains` (see
`docs/architecture/backend.md` -- "Backend yalnızca AI Core'u çağırır"), so
this is handed to the graph as a plain callable at construction time
instead, the same way `llm_client` is.
"""

from typing import List, Tuple

from app.domains.units.repository import UnitRepository
from app.infrastructure.database.session import AsyncSessionLocal


async def get_active_units_for_routing() -> List[Tuple[str, str]]:
    """Return `(name, description)` for every currently active unit.

    Returns:
        An empty list when no unit is configured yet -- callers must treat
        that as "nothing to route to", not as an error.
    """
    async with AsyncSessionLocal() as session:
        repository = UnitRepository(session)
        units = await repository.list_active()
        return [(unit.name, unit.description) for unit in units]
