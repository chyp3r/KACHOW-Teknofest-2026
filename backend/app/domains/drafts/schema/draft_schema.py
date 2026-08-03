from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DraftResponse(BaseModel):
    """One version of a drafted correspondence."""

    id: str = Field(description="Unique draft version ID.")
    session_id: str = Field(description="Conversation thread_id this draft belongs to.")
    document_id: Optional[str] = Field(default=None, description="Source document's storage_path, if any.")
    version: int = Field(description="1-based version number within the conversation.")
    parent_draft_id: Optional[str] = Field(default=None, description="The version this one revised, if any.")
    content: str = Field(description="The draft text.")
    correspondence_type: Optional[str] = Field(default=None)
    routed_unit: Optional[str] = Field(default=None, description="Suggested routing unit, if resolved.")
    status: Optional[str] = Field(default=None, description="StepStatus value at the time this version was saved.")
    confidence_score: Optional[float] = Field(default=None)
    instructions: Optional[str] = Field(default=None, description="The request or revision instruction that produced this version.")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
