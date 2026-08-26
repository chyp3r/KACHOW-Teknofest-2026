from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

#: Frontend `ChatComposer`'ın tek bir AI mesajı üzerindeki kendi sınırını
#: (8000 karakter) gevşek biçimde yansıtır, ama insan-insana bir mesajın
#: pratikte daha kısa olması beklenir -- 4000, bir konuşma thread'inin
#: bir belge-yapıştırma hedefi olarak kullanılmasına davetiye çıkarmadan
#: bol yer bırakır.
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
    #: Okuma işaretçisinin ilerletileceği mesaj. Tüm konuşmayı okundu
    #: olarak işaretlemek için boş bırakın (çağrı anındaki en yeni
    #: mesaja ilerler).
    message_id: Optional[str] = None
