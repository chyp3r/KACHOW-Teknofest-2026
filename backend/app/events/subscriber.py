from app.events.event_bus import event_bus

def subscribe(event_type: str):
    """SOTA decorator to register event listeners to the global event bus."""
    def decorator(func):
        event_bus.subscribe(event_type, func)
        return func
    return decorator
