import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

class MCPClient:
    """SOTA Client connector for external Model Context Protocol (MCP) servers."""

    def __init__(self, name: str, command: str, args: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None):
        self.name = name
        self.server_params = StdioServerParameters(
            command=command,
            args=args or [],
            env=env
        )
        self.session: Optional[ClientSession] = None

    @asynccontextmanager
    async def connect(self):
        """Asynchronously connect to the MCP server and initialize a session."""
        logger.info(f"Connecting to MCP server '{self.name}' using command: {self.server_params.command}")
        try:
            async with stdio_client(self.server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.session = session
                    logger.info(f"Successfully initialized session with MCP server '{self.name}'")
                    yield session
        except Exception as e:
            logger.error(f"Failed to connect to MCP server '{self.name}': {e}", exc_info=True)
            raise
        finally:
            self.session = None
