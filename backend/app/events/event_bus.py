import asyncio
import logging
from typing import Any, Callable, Dict, List, Union
from app.events.event import BaseEvent

logger = logging.getLogger(__name__)

EventListener = Callable[[Any], Union[None, Any]]

class EventBus:
    """SOTA asynchronous in-memory event bus for event-driven coordination."""

    def __init__(self):
        self._listeners: Dict[str, List[EventListener]] = {}

    def subscribe(self, event_type: str, listener: EventListener) -> None:
        """Subscribe a listener callable to a specific event type."""
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(listener)
        logger.debug(f"Subscribed listener to event: {event_type}")

    def unsubscribe(self, event_type: str, listener: EventListener) -> None:
        """Unsubscribe a listener callable from an event type."""
        if event_type in self._listeners:
            try:
                self._listeners[event_type].remove(listener)
                logger.debug(f"Unsubscribed listener from event: {event_type}")
            except ValueError:
                pass

    async def publish(self, event: BaseEvent) -> None:
        """Publish an event to all subscribed listeners asynchronously."""
        event_type = event.event_type
        listeners = self._listeners.get(event_type, [])
        
        if not listeners:
            logger.debug(f"No listeners registered for event: {event_type}")
            return

        logger.info(f"Publishing event '{event_type}' ({event.event_id}) to {len(listeners)} listeners")
        
        tasks = []
        for listener in listeners:
            if asyncio.iscoroutinefunction(listener):
                tasks.append(asyncio.create_task(self._safe_execute_async(listener, event)))
            else:
                self._execute_sync(listener, event)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_execute_async(self, listener: EventListener, event: BaseEvent) -> None:
        try:
            await listener(event)
        except Exception as e:
            logger.error(f"Error in async event listener for event {event.event_type}: {e}", exc_info=True)

    def _execute_sync(self, listener: EventListener, event: BaseEvent) -> None:
        try:
            listener(event)
        except Exception as e:
            logger.error(f"Error in sync event listener for event {event.event_type}: {e}", exc_info=True)

# Global singleton event bus instance
event_bus = EventBus()
