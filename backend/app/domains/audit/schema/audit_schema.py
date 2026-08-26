from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    """Tek bir `audit_log` satırı için Pydantic şeması."""

    model_config = {"from_attributes": True}

    id: str
    company_id: Optional[str] = None
    seq: int
    actor_user_id: Optional[str] = None
    actor_role: Optional[str] = None
    acting_as_company_id: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    decision: str
    reason: Optional[str] = None
    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None
    correlation_id: Optional[str] = None
    created_at: datetime


class ChainVerificationResponse(BaseModel):
    """`GET /audit/verify`'ın sonucu için Pydantic şeması."""

    valid: bool
    rows_checked: int
    broken_at_seq: Optional[int] = None
    reason: Optional[str] = None
