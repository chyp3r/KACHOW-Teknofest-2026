import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Basic FastMCP server instance for exposing local tools if needed
mcp_server = FastMCP("Kachow-Internal-Server")

@mcp_server.tool()
def status() -> str:
    """Check the status of the internal MCP server."""
    return "healthy"
