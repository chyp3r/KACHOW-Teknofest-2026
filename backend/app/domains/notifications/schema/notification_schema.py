from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    """Pydantic schema for one `notifications` row -- also the exact JSON
    payload published to Redis for the SSE stream (see
    `app.domains.notifications.service.NotificationService.create`)."""

    model_config = {"from_attributes": True}

    id: str
    type: str
    title: str
    body: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    read_at: Optional[datetime] = None
    created_at: datetime
