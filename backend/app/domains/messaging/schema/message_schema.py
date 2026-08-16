from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

#: Mirrors the frontend `ChatComposer`'s own cap on a single AI message
#: (8000 chars) loosely, but a human-to-human message is expected to be
#: shorter in practice -- 4000 leaves ample room without inviting a
#: conversation thread to be used as a document-paste target.
MESSAGE_BODY_MAX_LENGTH = 4000


class MessageCreateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=MESSAGE_BODY_MAX_LENGTH)


class MessageResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    conversation_id: str
    sender_id: Optional[str] = None
    sender_username: Optional[str] = None
    kind: str
    body: str
    artifact_transfer_id: Optional[str] = None
    created_at: datetime


class MarkReadRequest(BaseModel):
    #: The message to advance the read pointer to. Omit to mark the whole
    #: conversation read (advances to the newest message at call time).
    message_id: Optional[str] = None
