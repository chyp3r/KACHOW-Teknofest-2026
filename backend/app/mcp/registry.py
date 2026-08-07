"""Which external MCP servers this application knows about.

`MCPManager` can talk to any server; this module decides which ones exist. Kept
separate so registration is a small, greppable list rather than a call buried in
startup, and so a server can be switched off by configuration without touching
code.

One server today: `mevzuat-mcp` (github.com/saidsurucu/mevzuat-mcp, MIT), which
queries mevzuat.gov.tr and bedesten.adalet.gov.tr. Two runtime callers share it,
gated by two independent settings (see `core.config.Settings` for the full
reasoning):

* `app.ai.retrieval.mcp_mevzuat` -- document analysis's legislation retrieval,
  live by default (`MEVZUAT_SOURCE="mcp"`), falling back to the committed
  corpus on failure. Never touches `check_required_fields`: that is set
  subtraction over a rule table with hard-coded article numbers, so the
  compliance decision stays deterministic regardless of which source served
  the citations.
* `app.ai.tools.mevzuat_tools` -- the assistant's live lookup tool, off by
  default (`MEVZUAT_MCP_ENABLED`), offered as an escalation when the local
  corpus tool finds nothing.

`register_servers()` below registers the server whenever *either* setting
wants it, so the documented default keeps working even though the two
settings' defaults disagree (`MEVZUAT_SOURCE="mcp"` but
`MEVZUAT_MCP_ENABLED=False`).

The same server is also used off-line, by `scripts/fetch_mevzuat_corpus.py`, to
build the committed corpus that both the "local" source above and the assistant's
local-corpus tool read from.
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

    if settings.MEVZUAT_MCP_ENABLED or settings.MEVZUAT_SOURCE == "mcp":
        mcp_manager.register_server(
            name=MEVZUAT_SERVER,
            command=settings.MEVZUAT_MCP_COMMAND,
            args=settings.mevzuat_mcp_args,
        )
        registered.append(MEVZUAT_SERVER)
        logger.info(
            "Registered MCP server '%s' (command: %s). MEVZUAT_MCP_ENABLED=%s, "
            "MEVZUAT_SOURCE=%s.",
            MEVZUAT_SERVER,
            settings.MEVZUAT_MCP_COMMAND,
            settings.MEVZUAT_MCP_ENABLED,
            settings.MEVZUAT_SOURCE,
        )
    else:
        logger.debug(
            "Neither MEVZUAT_MCP_ENABLED nor MEVZUAT_SOURCE=mcp is set; nothing "
            "reaches mevzuat-mcp and legislation stays fully local."
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
