from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ConversationCreateRequest(BaseModel):
    """`POST /messaging/conversations` body -- discriminated by `kind`.

    A DM sets `participant_id` only; a group sets `title` and
    `participant_ids` only. One endpoint, not two, because "open or create
    a conversation" is a single concept to the caller -- the discriminator
    just picks which fields are relevant, the same way the frontend forms
    it maps to would.
    """

    kind: Literal["dm", "group"]
    participant_id: Optional[str] = Field(default=None, description="DM only: diğer katılımcı ID'si")
    title: Optional[str] = Field(default=None, min_length=1, max_length=200, description="Grup only")
    participant_ids: Optional[List[str]] = Field(
        default=None, description="Grup only: kurucu dışındaki üye ID'leri"
    )

    @model_validator(mode="after")
    def _check_shape(self) -> "ConversationCreateRequest":
        if self.kind == "dm":
            if not self.participant_id:
                raise ValueError("DM için participant_id gerekli.")
        else:
            if not self.title or not self.participant_ids:
                raise ValueError("Grup için title ve participant_ids gerekli.")
        return self


class ConversationUpdateRequest(BaseModel):
    """Group-only: rename or archive. A DM has no editable fields."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    is_archived: Optional[bool] = None


class ParticipantAddRequest(BaseModel):
    user_ids: List[str] = Field(min_length=1)


class ParticipantResponse(BaseModel):
    user_id: str
    username: str
    role_in_conversation: str
    joined_at: datetime
    left_at: Optional[datetime] = None


class ConversationResponse(BaseModel):
    """One conversation row, denormalized with the caller's own participant
    state (`unread_count`, `role_in_conversation`) and the other/all
    participants -- built by the service from several tables, never a
    direct `model_validate` off `ConversationModel` alone."""

    id: str
    kind: str
    title: Optional[str] = None
    last_message_at: Optional[datetime] = None
    is_archived: bool
    created_at: datetime
    participants: List[ParticipantResponse] = Field(default_factory=list)
    unread_count: int = 0
    role_in_conversation: str
