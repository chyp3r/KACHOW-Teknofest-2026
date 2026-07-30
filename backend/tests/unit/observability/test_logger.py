import json
import logging
from unittest.mock import patch
from app.observability.logger import JSONFormatter, setup_logging

def test_json_formatter():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="path/to/file.py",
        lineno=10,
        msg="Test message",
        args=(),
        exc_info=None
    )
    
    result = formatter.format(record)
    data = json.loads(result)
    
    assert data["logger"] == "test_logger"
    assert data["level"] == "INFO"
    assert data["message"] == "Test message"
    assert "timestamp" in data

def test_json_formatter_with_exception():
    formatter = JSONFormatter()
    try:
        1 / 0
    except Exception as e:
        import sys
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname="path/to/file.py",
        lineno=10,
        msg="Test message",
        args=(),
        exc_info=exc_info
    )
    
    result = formatter.format(record)
    data = json.loads(result)
    
    assert data["level"] == "ERROR"
    assert "exception" in data
    assert "ZeroDivisionError" in data["exception"]

def test_setup_logging_development():
    with patch("logging.getLogger") as mock_get_logger:
        root_logger = mock_get_logger.return_value
        root_logger.handlers = []
        
        setup_logging("development")
        
        root_logger.setLevel.assert_any_call(logging.DEBUG)
        root_logger.addHandler.assert_called_once()
        mock_get_logger.assert_any_call("uvicorn.access")

def test_setup_logging_production():
    with patch("logging.getLogger") as mock_get_logger:
        root_logger = mock_get_logger.return_value
        root_logger.handlers = []
        
        setup_logging("production")
        
        root_logger.setLevel.assert_any_call(logging.INFO)
        root_logger.addHandler.assert_called_once()
