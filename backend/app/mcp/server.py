import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Gerekirse yerel araçları dışa açmak için temel FastMCP sunucu örneği
mcp_server = FastMCP("Kachow-Internal-Server")

@mcp_server.tool()
def status() -> str:
    """Dahili MCP sunucusunun durumunu kontrol et."""
    return "healthy"
