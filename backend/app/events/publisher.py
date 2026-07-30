import logging
from app.events.event import BaseEvent
from app.events.event_bus import event_bus

logger = logging.getLogger(__name__)

class EventPublisher:
    """SOTA Event Publisher wrapping the EventBus for easy domain publishing."""

    @staticmethod
    async def publish(event: BaseEvent) -> None:
        """Publish an event to the global event bus."""
        logger.debug(f"EventPublisher publishing: {event.event_type} - {event.event_id}")
        await event_bus.publish(event)
