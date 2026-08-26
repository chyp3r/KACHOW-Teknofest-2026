from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    """Tek bir `notifications` satırı için Pydantic şeması -- ayrıca SSE
    akışı için Redis'e yayınlanan tam JSON payload'ı (bkz.
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
