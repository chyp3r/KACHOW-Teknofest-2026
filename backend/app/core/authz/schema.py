from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.authz.attributes import Action


class PermissionGrantCreate(BaseModel):
    """Pydantic schema for delegating a permission to a user (Admin/Manager only).

    The target user is the ``{user_id}`` path parameter of
    ``POST /users/{user_id}/permissions``, not a field here -- one row is
    always "this action, to this specific person", never a bulk operation.
    """

    action: str = Field(description="Örn. 'document:delete' -- bkz. app.core.authz.attributes.Action")
    resource_type: str = Field(description="Örn. 'document', 'draft', veya '*'")
    resource_selector: Dict[str, Any] = Field(
        default_factory=lambda: {"owner": "self"},
        description="{'any': true} | {'owner': 'self'} | {'id': '<resource_id>'}",
    )
    effect: str = Field(default="permit", description="'permit' veya 'deny'")
    priority: int = Field(default=0, ge=0, le=1000)
    valid_from: Optional[datetime] = Field(default=None)
    valid_until: Optional[datetime] = Field(default=None, description="Süreli/break-glass yetki için")
    reason: Optional[str] = Field(default=None, max_length=500)

    @field_validator("effect")
    @classmethod
    def _validate_effect(cls, value: str) -> str:
        if value not in ("permit", "deny"):
            raise ValueError("effect 'permit' veya 'deny' olmalı")
        return value

    @field_validator("action")
    @classmethod
    def _validate_action(cls, value: str) -> str:
        if value != "*" and value not in Action.ALL:
            raise ValueError(f"bilinmeyen action: {value!r}")
        return value


class PermissionGrantResponse(BaseModel):
    """Pydantic schema for a persisted permission grant."""

    id: str
    company_id: str
    subject_type: str
    subject_id: str
    action: str
    resource_type: str
    resource_selector: Dict[str, Any]
    effect: str
    priority: int
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    granted_by: str
    revoked_at: Optional[datetime] = None
    reason: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
