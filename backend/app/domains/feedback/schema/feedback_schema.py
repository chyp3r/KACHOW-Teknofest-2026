from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

#: Girdi tarafında kapalı küme (bu şemanın koruduğu tek yazma yolunda
#: çöp verinin önlenmesi) -- DB sütununun kendisi, `NotificationModel.type`
#: kuralına uygun şekilde gevşek bir string olarak kalır, böylece
#: oylanabilir yeni bir yüzey yalnızca bu tek dosyanın güncellenmesini
#: gerektirir, bir migration değil.
TargetKind = Literal["draft", "revision", "assist_reply", "routing"]
Signal = Literal["like", "dislike"]


class FeedbackVoteRequest(BaseModel):
    """Bir oy vermek (veya tekrar vermek) için Pydantic şeması.

    `content`, oylanan tam metindir -- sunucu tarafında `content_hash`'e
    hash'lenir ve kendisi asla kalıcı hale getirilmez (bkz. `FeedbackModel`'ın
    docstring'i). Frontend bu metne zaten sahiptir (ekranda görünen odur),
    bu yüzden oy vermek için ekstra bir fetch gerekmez.
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
    """Tek bir geri bildirim satırı için Pydantic şeması."""

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
    """`GET /companies/{id}/feedback/stats` için Pydantic şeması."""

    total: int
    likes: int
    dislikes: int
    by_target_kind: dict[str, int]
