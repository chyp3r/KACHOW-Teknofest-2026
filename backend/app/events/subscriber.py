from app.events.event_bus import event_bus

def subscribe(event_type: str):
    """Event listener'ları global event bus'a kaydeden decorator."""
    def decorator(func):
        event_bus.subscribe(event_type, func)
        return func
    return decorator
