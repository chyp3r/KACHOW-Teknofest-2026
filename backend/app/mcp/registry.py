"""Which external MCP servers this application knows about.

`MCPManager` can talk to any server; this module decides which ones exist. Kept
separate so registration is a small, greppable list rather than a call buried in
startup, and so a server can be switched off by configuration without touching
code.

One server today: `mevzuat-mcp` (github.com/saidsurucu/mevzuat-mcp, MIT), which
queries mevzuat.gov.tr and bedesten.adalet.gov.tr. It backs a live legislation
lookup for the assistant and nothing else. In particular it does **not** feed the
document analysis pipeline: `check_required_fields` is set subtraction over a rule
table with hard-coded article numbers, and keeping a live external service out of
that is what makes the same evrak yield byte-identical output on every run.

The same server is also used off-line, by `scripts/fetch_mevzuat_corpus.py`, to
build the committed corpus. That path is what the scored requirements depend on;
this one is a convenience for questions the corpus does not cover.
"""

import logging

from app.core.config import settings
from app.mcp.manager import mcp_manager

logger = logging.getLogger(__name__)

#: Registered name for the legislation server, used by every call site.
MEVZUAT_SERVER = "mevzuat"


def register_servers() -> list[str]:
    """Register every configured MCP server with the shared manager.

    Idempotent: re-registering replaces the client rather than accumulating
    duplicates, so calling this from both startup and a test fixture is safe.

    Returns:
        The names of the servers now registered.
    """
    registered: list[str] = []

    if settings.MEVZUAT_MCP_ENABLED:
        mcp_manager.register_server(
            name=MEVZUAT_SERVER,
            command=settings.MEVZUAT_MCP_COMMAND,
            args=settings.mevzuat_mcp_args,
        )
        registered.append(MEVZUAT_SERVER)
        logger.info(
            "Registered MCP server '%s' (command: %s). Live legislation lookup "
            "is available to the assistant.",
            MEVZUAT_SERVER,
            settings.MEVZUAT_MCP_COMMAND,
        )
    else:
        logger.debug(
            "MEVZUAT_MCP_ENABLED is off; the assistant answers legislation "
            "questions from the committed corpus only."
        )

    return registered


def is_registered(name: str) -> bool:
    """Report whether a server is available to call.

    Args:
        name: Registered server name.

    Returns:
        True when the server was registered.
    """
    return name in mcp_manager.clients
