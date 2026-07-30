import pytest
from unittest.mock import patch, MagicMock

import app.observability.tracer as tracer
from app.observability.tracer import get_langfuse_callback

@pytest.fixture(autouse=True)
def reset_callback():
    tracer._callback_handler = None
    yield
    tracer._callback_handler = None

def test_get_langfuse_callback_disabled(monkeypatch):
    monkeypatch.setattr("app.observability.tracer.settings.LANGFUSE_PUBLIC_KEY", None)
    monkeypatch.setattr("app.observability.tracer.settings.LANGFUSE_SECRET_KEY", None)
    
    result = get_langfuse_callback()
    assert result is None

@patch("app.observability.tracer.CallbackHandler")
def test_get_langfuse_callback_success(mock_handler, monkeypatch):
    monkeypatch.setattr("app.observability.tracer.settings.LANGFUSE_PUBLIC_KEY", "pub")
    monkeypatch.setattr("app.observability.tracer.settings.LANGFUSE_SECRET_KEY", "sec")
    monkeypatch.setattr("app.observability.tracer.settings.LANGFUSE_HOST", "host")
    
    mock_instance = MagicMock()
    mock_handler.return_value = mock_instance
    
    result1 = get_langfuse_callback()
    assert result1 == mock_instance
    mock_handler.assert_called_once_with(public_key="pub", secret_key="sec", host="host")
    
    # Check singleton behavior
    result2 = get_langfuse_callback()
    assert result2 == mock_instance
    mock_handler.assert_called_once()  # Still called once

@patch("app.observability.tracer.CallbackHandler")
def test_get_langfuse_callback_exception(mock_handler, monkeypatch):
    monkeypatch.setattr("app.observability.tracer.settings.LANGFUSE_PUBLIC_KEY", "pub")
    monkeypatch.setattr("app.observability.tracer.settings.LANGFUSE_SECRET_KEY", "sec")
    
    mock_handler.side_effect = Exception("Init failed")
    
    result = get_langfuse_callback()
    assert result is None
