import pytest

from app.mcp.server import status

def test_mcp_server_status():
    result = status()
    assert result == "healthy"
