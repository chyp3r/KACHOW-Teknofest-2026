import logging
import time
from typing import Any, Dict, List, Optional
from app.mcp.client import MCPClient
from app.observability.ai_metrics import MCP_CALL_DURATION

logger = logging.getLogger(__name__)

class MCPManager:
    """Birden çok MCP istemcisini keşfetmek, düzenlemek ve çağrıları yönlendirmek için SOTA yönetici."""

    def __init__(self):
        self.clients: Dict[str, MCPClient] = {}

    def register_server(
        self,
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        """Yönetilecek harici bir MCP sunucusunu kaydet."""
        self.clients[name] = MCPClient(name=name, command=command, args=args, env=env)
        logger.info(f"Registered MCP server '{name}' in manager.")

    async def list_tools(self, server_name: str) -> List[Any]:
        """Kayıtlı belirli bir MCP sunucusundan kullanılabilir araçları listele."""
        client = self.clients.get(server_name)
        if not client:
            raise ValueError(f"MCP server '{server_name}' is not registered.")
        
        async with client.connect() as session:
            result = await session.list_tools()
            return result.tools

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: Dict[str, Any]
    ) -> Any:
        """Kayıtlı belirli bir MCP sunucusunda bir aracı çalıştır."""
        client = self.clients.get(server_name)
        if not client:
            raise ValueError(f"MCP server '{server_name}' is not registered.")

        # Bu, her MCP çağrısının geçtiği tek boğaz noktası -- burada
        # ölçmek, çağıranların (mevzuat_client.py, mevzuat_tools.py, ...)
        # her biri kendi zamanlamasını ayrı ayrı eklemesini gerektirmez.
        start = time.perf_counter()
        status = "error"
        try:
            async with client.connect() as session:
                logger.info(f"Calling tool '{tool_name}' on MCP server '{server_name}'...")
                result = await session.call_tool(name=tool_name, arguments=arguments)
            status = "success"
            return result
        finally:
            MCP_CALL_DURATION.labels(
                server=server_name, tool=tool_name, status=status
            ).observe(time.perf_counter() - start)

# Tekil (singleton) yönetici örneği
mcp_manager = MCPManager()
