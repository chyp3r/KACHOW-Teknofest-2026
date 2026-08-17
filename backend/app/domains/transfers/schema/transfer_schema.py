from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.domains.transfers.service import MAX_GROUP_TRANSFER_RECIPIENTS


class TransferSendRequest(BaseModel):
    """`POST /transfers/send` body -- the manual chat-initiated send.

    Recipient is always an explicit id here: this channel is fed by
    `UserSearchDrawer`/`PersonPickerBody` (Faz 2), which already resolves a
    name to a user before the request is ever made. Name-based resolution
    (`RecipientResolutionService`) exists for the Faz 4 AI channel, not
    this one.
    """

    recipient_id: str = Field(description="Alıcı kullanıcı ID'si")
    artifact_kind: Literal["draft", "document"]
    source_artifact_id: str = Field(description="drafts.id veya evrak storage_path'i")
    #: Pinned at send time for a draft (see `ArtifactTransferModel.
    #: source_version`'s own docstring); ignored for a document.
    source_version: Optional[int] = None
    #: Optional caller-supplied idempotency token -- a retried request with
    #: the same key returns the original transfer instead of re-executing.
    idempotency_key: Optional[str] = Field(default=None, max_length=200)


class GroupTransferSendRequest(BaseModel):
    """`POST /transfers/send-group` body -- chat/REST-only fan-out to
    several recipients at once (Faz 5, #205). There is no AI-channel
    equivalent of this request; see `ArtifactTransferService.execute_group`'s
    own docstring.
    """

    recipient_ids: List[str] = Field(
        min_length=1,
        max_length=MAX_GROUP_TRANSFER_RECIPIENTS,
        description="Alıcı kullanıcı ID'leri",
    )
    artifact_kind: Literal["draft", "document"]
    source_artifact_id: str = Field(description="drafts.id veya evrak storage_path'i")
    source_version: Optional[int] = None
    #: Combined with each recipient id to derive that recipient's own
    #: idempotency key -- see `GroupTransferCommand.idempotency_key_prefix`.
    idempotency_key_prefix: Optional[str] = Field(default=None, max_length=200)


class GroupTransferResultItemResponse(BaseModel):
    recipient_id: str
    status: str
    transfer_id: Optional[str] = None
    reason: Optional[str] = None


class TransferResponse(BaseModel):
    id: str
    artifact_kind: str
    source_artifact_id: str
    source_version: Optional[int] = None
    snapshot_ref: Optional[str] = None
    sender_id: str
    recipient_id: str
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    channel: str
    ai_suggested: bool
    cross_unit: bool
    policy_decision: str
    policy_reason: Optional[str] = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
