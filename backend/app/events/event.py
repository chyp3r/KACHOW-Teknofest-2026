from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4
from pydantic import BaseModel, Field

class BaseEvent(BaseModel):
    """SOTA base event structure for loose coupling between domains."""
    event_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique ID of the event")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Time of the event")
    event_type: str = Field(description="Name/type of the event")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event data payload")

class DocumentUploadedEvent(BaseEvent):
    event_type: str = "document.uploaded"

class DocumentClassifiedEvent(BaseEvent):
    event_type: str = "document.classified"

class DocumentAnalyzedEvent(BaseEvent):
    event_type: str = "document.analyzed"

class DraftCreatedEvent(BaseEvent):
    event_type: str = "draft.created"

class DocumentRoutedEvent(BaseEvent):
    event_type: str = "document.routed"

class UserCreatedEvent(BaseEvent):
    event_type: str = "user.created"
