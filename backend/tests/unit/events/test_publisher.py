import pytest
from unittest.mock import patch, AsyncMock
from app.events.publisher import EventPublisher
from app.events.event import BaseEvent

class DummyEvent(BaseEvent):
    event_type: str = "dummy.event"

@pytest.mark.asyncio
async def test_event_publisher():
    with patch("app.events.publisher.event_bus") as mock_bus:
        mock_bus.publish = AsyncMock()
        event = DummyEvent()
        await EventPublisher.publish(event)
        
        mock_bus.publish.assert_called_once_with(event)
