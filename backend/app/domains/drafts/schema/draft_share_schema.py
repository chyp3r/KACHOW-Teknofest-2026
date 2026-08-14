from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class DraftSendRequest(BaseModel):
    """Pydantic schema for sending one draft version to one or more recipients."""

    recipient_ids: List[str] = Field(min_length=1, description="Alıcı kullanıcı ID'leri")
    message: Optional[str] = Field(default=None, max_length=2000)


class DraftShareRespondRequest(BaseModel):
    """Pydantic schema for accepting or rejecting a shared draft."""

    response_note: Optional[str] = Field(default=None, max_length=2000)


class DraftShareResponse(BaseModel):
    """Pydantic schema for one draft_shares row, joined with the draft's own content
    so a recipient can read what was sent without a separate `GET /drafts/{id}` call
    (which their ownership wouldn't pass anyway -- see `draft_share_service.py`'s
    module docstring)."""

    model_config = {"from_attributes": True}

    id: str
    draft_id: str
    sender_id: str
    recipient_id: str
    suggested_unit_id: Optional[str] = None
    message: Optional[str] = None
    status: str
    responded_at: Optional[datetime] = None
    response_note: Optional[str] = None
    created_at: datetime
    #: Denormalized from the joined `DraftModel` -- populated by the service,
    #: not a real column on `draft_shares`.
    content: Optional[str] = None
    correspondence_type: Optional[str] = None
    destination: Optional[str] = None
