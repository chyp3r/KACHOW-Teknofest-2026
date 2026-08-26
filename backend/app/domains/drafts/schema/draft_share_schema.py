from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class DraftSendRequest(BaseModel):
    """Bir taslak versiyonunu bir veya birden fazla alıcıya göndermek için Pydantic şeması."""

    recipient_ids: List[str] = Field(min_length=1, description="Alıcı kullanıcı ID'leri")
    message: Optional[str] = Field(default=None, max_length=2000)


class DraftShareRespondRequest(BaseModel):
    """Paylaşılan bir taslağı kabul etmek veya reddetmek için Pydantic şeması."""

    response_note: Optional[str] = Field(default=None, max_length=2000)


class DraftShareResponse(BaseModel):
    """Bir draft_shares satırı için, alıcının ayrı bir `GET /drafts/{id}` çağrısı
    yapmadan (ki sahiplik kontrolünden zaten geçemezdi -- bkz.
    `draft_share_service.py`'nin modül docstring'i) neyin gönderildiğini
    okuyabilmesi için taslağın kendi içeriğiyle join edilmiş Pydantic şeması."""

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
    #: Join edilmiş `DraftModel`'den denormalize edilmiştir -- servis
    #: tarafından doldurulur, `draft_shares` üzerinde gerçek bir sütun
    #: değildir.
    content: Optional[str] = None
    correspondence_type: Optional[str] = None
    destination: Optional[str] = None
