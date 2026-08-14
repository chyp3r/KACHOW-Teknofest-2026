from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class DocumentPoolResponse(BaseModel):
    """Pydantic schema for a pool's own metadata."""

    id: str
    owner_type: str
    owner_id: str
    name: str
    is_default: bool

    model_config = {"from_attributes": True}


class DocumentPoolItemResponse(BaseModel):
    """Pydantic schema for one pool item, joined with its document's file name."""

    id: str
    pool_id: str
    document_id: str
    file_name: Optional[str] = Field(default=None, description="Belgenin dosya adı")
    added_by: str
    source: str
    note: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PoolItemCreate(BaseModel):
    """Pydantic schema for pushing one document into a specific pool."""

    document_id: str = Field(description="İtilecek evrakın storage_path'i")
    note: Optional[str] = Field(default=None, max_length=1000)


class PoolPushRequest(BaseModel):
    """Pydantic schema for a bulk push: one document, several recipients or a whole unit."""

    document_id: str = Field(description="İtilecek evrakın storage_path'i")
    recipient_ids: Optional[List[str]] = Field(default=None, description="Alıcı kullanıcı ID'leri")
    unit_id: Optional[str] = Field(default=None, description="Bu birimin tüm üyelerine gönder")
    note: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "PoolPushRequest":
        if bool(self.recipient_ids) == bool(self.unit_id):
            raise ValueError("recipient_ids veya unit_id alanlarından tam olarak biri verilmeli.")
        return self


class PoolPushResultItem(BaseModel):
    """Pydantic schema for one recipient's outcome within a bulk push."""

    user_id: str
    status: str = Field(description="'pushed' | 'denied_clearance' | 'not_found'")
    reason: Optional[str] = None
