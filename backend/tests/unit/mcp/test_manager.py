import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.mcp.manager import MCPManager
from app.mcp.client import MCPClient

@pytest.fixture
def mcp_manager():
    return MCPManager()

def test_mcp_manager_init(mcp_manager):
    assert mcp_manager.clients == {}

def test_mcp_manager_register_server(mcp_manager):
    mcp_manager.register_server("test_server", "dummy_cmd", ["--arg"], {"ENV": "1"})
    assert "test_server" in mcp_manager.clients
    client = mcp_manager.clients["test_server"]
    assert isinstance(client, MCPClient)
    assert client.name == "test_server"
    assert client.server_params.command == "dummy_cmd"
    assert client.server_params.args == ["--arg"]
    assert client.server_params.env == {"ENV": "1"}

@pytest.mark.asyncio
async def test_mcp_manager_list_tools_success(mcp_manager):
    mcp_manager.register_server("test_server", "dummy_cmd")
    
    mock_session = AsyncMock()
    mock_tools_result = MagicMock()
    mock_tools_result.tools = ["tool1", "tool2"]
    mock_session.list_tools.return_value = mock_tools_result
    
    mock_client_context = AsyncMock()
    mock_client_context.__aenter__.return_value = mock_session
    
    with patch.object(MCPClient, "connect", return_value=mock_client_context):
        tools = await mcp_manager.list_tools("test_server")
        assert tools == ["tool1", "tool2"]
        mock_session.list_tools.assert_called_once()

@pytest.mark.asyncio
async def test_mcp_manager_list_tools_unregistered(mcp_manager):
    with pytest.raises(ValueError, match="is not registered"):
        await mcp_manager.list_tools("non_existent_server")

@pytest.mark.asyncio
async def test_mcp_manager_call_tool_success(mcp_manager):
    mcp_manager.register_server("test_server", "dummy_cmd")
    
    mock_session = AsyncMock()
    mock_session.call_tool.return_value = "tool_result"
    
    mock_client_context = AsyncMock()
    mock_client_context.__aenter__.return_value = mock_session
    
    with patch.object(MCPClient, "connect", return_value=mock_client_context):
        result = await mcp_manager.call_tool("test_server", "tool1", {"arg": "val"})
        assert result == "tool_result"
        mock_session.call_tool.assert_called_once_with(name="tool1", arguments={"arg": "val"})

@pytest.mark.asyncio
async def test_mcp_manager_call_tool_unregistered(mcp_manager):
    with pytest.raises(ValueError, match="is not registered"):
        await mcp_manager.call_tool("non_existent_server", "tool1", {})
