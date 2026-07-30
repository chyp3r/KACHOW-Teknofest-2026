import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from app.observability.metrics import init_metrics

def test_init_metrics():
    app = FastAPI()
    with patch("app.observability.metrics.Instrumentator") as mock_instrumentator:
        mock_instance = MagicMock()
        mock_instrumentator.return_value = mock_instance
        mock_instance.instrument.return_value = mock_instance
        
        init_metrics(app)
        
        mock_instrumentator.assert_called_once()
        mock_instance.instrument.assert_called_once_with(app)
        mock_instance.expose.assert_called_once_with(app, endpoint="/metrics")
