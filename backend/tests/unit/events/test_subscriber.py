import pytest
from unittest.mock import patch
from app.events.subscriber import subscribe

def test_subscribe_decorator():
    with patch("app.events.subscriber.event_bus") as mock_bus:
        @subscribe("dummy.event")
        def dummy_listener(event):
            pass
            
        mock_bus.subscribe.assert_called_once_with("dummy.event", dummy_listener)
