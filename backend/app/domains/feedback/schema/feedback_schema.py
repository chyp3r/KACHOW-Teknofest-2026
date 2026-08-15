from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

#: Input-side closed set (garbage prevention on the one write path this
#: schema guards) -- the DB column itself stays a loose string, matching
#: `NotificationModel.type`'s convention, so a new rateable surface only
#: ever needs this one file updated, not a migration.
TargetKind = Literal["draft", "revision", "assist_reply", "routing"]
Signal = Literal["like", "dislike"]


class FeedbackVoteRequest(BaseModel):
    """Pydantic schema for casting (or re-casting) a vote.

    `content` is the exact rated text -- hashed server-side into
    `content_hash` and never itself persisted (see `FeedbackModel`'s
    docstring). The frontend already has this text in hand (it is what is
    on screen), so no extra fetch is needed to vote.
    """

    target_kind: TargetKind
    signal: Signal
    content: str = Field(min_length=1, description="Oylanan metnin kendisi -- sunucuda hash'lenir.")
    comment: Optional[str] = Field(default=None, max_length=2000)
    dimensions: Optional[dict] = Field(
        default=None, description="Opsiyonel boyut etiketleri, örn. {'uslup': true}."
    )
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    draft_id: Optional[str] = None
    context: Optional[dict] = Field(
        default=None, description="Anlık bağlam kopyası, örn. correspondence_type/confidence_score."
    )


class FeedbackResponse(BaseModel):
    """Pydantic schema for one feedback row."""

    model_config = {"from_attributes": True}

    id: str
    target_kind: str
    signal: str
    comment: Optional[str] = None
    dimensions: Optional[dict] = None
    content_hash: str
    context: Optional[dict] = None
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    draft_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class FeedbackStatsResponse(BaseModel):
    """Pydantic schema for `GET /companies/{id}/feedback/stats`."""

    total: int
    likes: int
    dislikes: int
    by_target_kind: dict[str, int]
