import pytest
from unittest.mock import AsyncMock, patch

from app.mcp.client import MCPClient
from mcp.client.stdio import StdioServerParameters

@pytest.fixture
def mcp_client():
    return MCPClient(
        name="test_server",
        command="dummy_cmd",
        args=["--arg1"],
        env={"TEST": "1"}
    )

def test_mcp_client_init(mcp_client):
    assert mcp_client.name == "test_server"
    assert isinstance(mcp_client.server_params, StdioServerParameters)
    assert mcp_client.server_params.command == "dummy_cmd"
    assert mcp_client.server_params.args == ["--arg1"]
    assert mcp_client.server_params.env == {"TEST": "1"}
    assert mcp_client.session is None

@pytest.mark.asyncio
async def test_mcp_client_connect_success(mcp_client):
    mock_session = AsyncMock()
    mock_session_context = AsyncMock()
    mock_session_context.__aenter__.return_value = mock_session
    
    mock_stdio_context = AsyncMock()
    mock_stdio_context.__aenter__.return_value = (AsyncMock(), AsyncMock())
    
    with patch("app.mcp.client.stdio_client", return_value=mock_stdio_context), \
         patch("app.mcp.client.ClientSession", return_value=mock_session_context):
        
        async with mcp_client.connect() as session:
            assert session == mock_session
            assert mcp_client.session == mock_session
            mock_session.initialize.assert_called_once()
            
        assert mcp_client.session is None

@pytest.mark.asyncio
async def test_mcp_client_connect_failure(mcp_client):
    mock_stdio_context = AsyncMock()
    mock_stdio_context.__aenter__.side_effect = Exception("Connection Failed")
    
    with patch("app.mcp.client.stdio_client", return_value=mock_stdio_context):
        with pytest.raises(Exception, match="Connection Failed"):
            async with mcp_client.connect() as _:
                pass
        
        assert mcp_client.session is None
