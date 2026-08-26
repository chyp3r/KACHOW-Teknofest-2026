import logging
from app.events.event import BaseEvent
from app.events.event_bus import event_bus

logger = logging.getLogger(__name__)

class EventPublisher:
    """Domain'lerin kolayca event yayınlaması için EventBus'ı saran Event Publisher."""

    @staticmethod
    async def publish(event: BaseEvent) -> None:
        """Bir event'i global event bus'a yayınlar."""
        logger.debug(f"EventPublisher publishing: {event.event_type} - {event.event_id}")
        await event_bus.publish(event)
