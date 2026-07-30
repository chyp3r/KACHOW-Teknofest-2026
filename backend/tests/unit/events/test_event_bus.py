import pytest
from app.events.event_bus import EventBus
from app.events.event import BaseEvent

class DummyEvent(BaseEvent):
    event_type: str = "dummy.event"

@pytest.fixture
def bus():
    return EventBus()

@pytest.mark.asyncio
async def test_subscribe_and_publish_sync(bus):
    calls = []
    def sync_listener(event):
        calls.append(event)
    
    bus.subscribe("dummy.event", sync_listener)
    event = DummyEvent()
    await bus.publish(event)
    
    assert len(calls) == 1
    assert calls[0] == event

@pytest.mark.asyncio
async def test_subscribe_and_publish_async(bus):
    calls = []
    async def async_listener(event):
        calls.append(event)
    
    bus.subscribe("dummy.event", async_listener)
    event = DummyEvent()
    await bus.publish(event)
    
    assert len(calls) == 1
    assert calls[0] == event

@pytest.mark.asyncio
async def test_unsubscribe(bus):
    calls = []
    def sync_listener(event):
        calls.append(event)
    
    bus.subscribe("dummy.event", sync_listener)
    bus.unsubscribe("dummy.event", sync_listener)
    
    # Also test unsubscribe when not in list
    bus.unsubscribe("dummy.event", sync_listener)
    
    # Also test unsubscribe when event_type doesn't exist
    bus.unsubscribe("non.existent", sync_listener)
    
    event = DummyEvent()
    await bus.publish(event)
    
    assert len(calls) == 0

@pytest.mark.asyncio
async def test_publish_no_listeners(bus):
    event = DummyEvent()
    await bus.publish(event)  # Should not raise any error

@pytest.mark.asyncio
async def test_publish_sync_exception(bus, caplog):
    def sync_listener(event):
        raise ValueError("Sync error")
    
    bus.subscribe("dummy.event", sync_listener)
    event = DummyEvent()
    
    await bus.publish(event)
    assert "Sync error" in caplog.text
    assert "Error in sync event listener" in caplog.text

@pytest.mark.asyncio
async def test_publish_async_exception(bus, caplog):
    async def async_listener(event):
        raise ValueError("Async error")
    
    bus.subscribe("dummy.event", async_listener)
    event = DummyEvent()
    
    await bus.publish(event)
    assert "Async error" in caplog.text
    assert "Error in async event listener" in caplog.text
