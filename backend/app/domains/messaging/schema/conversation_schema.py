from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ConversationCreateRequest(BaseModel):
    """`POST /messaging/conversations` gövdesi -- `kind`'a göre ayrıştırılır.

    Bir DM yalnızca `participant_id`'yi ayarlar; bir grup yalnızca
    `title` ve `participant_ids`'i ayarlar. İki değil tek bir endpoint,
    çünkü "bir konuşmayı aç ya da oluştur" çağıran için tek bir kavramdır
    -- ayrıştırıcı yalnızca hangi alanların ilgili olduğunu seçer,
    eşlendiği frontend formlarının yapacağı gibi.
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
    """Yalnızca grup: yeniden adlandırma veya arşivleme. Bir DM'in
    düzenlenebilir alanı yoktur."""

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
    """Çağıranın kendi katılımcı durumuyla (`unread_count`,
    `role_in_conversation`) ve diğer/tüm katılımcılarla denormalize
    edilmiş tek bir konuşma satırı -- servis tarafından birden çok
    tablodan oluşturulur, asla tek başına `ConversationModel`'den
    doğrudan bir `model_validate` değildir."""

    id: str
    kind: str
    title: Optional[str] = None
    last_message_at: Optional[datetime] = None
    is_archived: bool
    created_at: datetime
    participants: List[ParticipantResponse] = Field(default_factory=list)
    unread_count: int = 0
    role_in_conversation: str
