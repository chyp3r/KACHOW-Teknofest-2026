from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class DraftDestinationUpdateRequest(BaseModel):
    """Override a draft version's routed unit -- see
    `DraftService.update_destination`."""

    destination: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "Yeni birim adı. Şirketin tanımlı birimlerinden biri, ya da serbest metin "
            "(eşleşen bir birim yoksa yalnızca isim olarak saklanır)."
        ),
    )


class DraftResponse(BaseModel):
    """One persisted draft version (see `DraftModel`)."""

    model_config = {"from_attributes": True}

    id: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    document_id: Optional[str] = None
    version: int
    parent_draft_id: Optional[str] = None
    content: str
    correspondence_type: Optional[str] = None
    destination: Optional[str] = None
    status: Optional[str] = None
    confidence_score: Optional[float] = None
    requires_human_approval: Optional[bool] = None
    attempts: Optional[int] = None
    verification: Optional[dict[str, Any]] = Field(default=None)
    judge: Optional[dict[str, Any]] = Field(default=None)
    missing_information: Optional[list[Any]] = Field(default=None)
    instructions: Optional[str] = None
    created_at: datetime
    updated_at: datetime
