from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.domains.transfers.service import MAX_GROUP_TRANSFER_RECIPIENTS


class TransferSendRequest(BaseModel):
    """`POST /transfers/send` gövdesi -- manuel, sohbetten başlatılan gönderim.

    Alıcı burada her zaman açık bir id'dir: bu kanal, istek yapılmadan
    önce zaten bir ismi bir kullanıcıya çözümleyen
    `UserSearchDrawer`/`PersonPickerBody` (Faz 2) tarafından beslenir.
    İsim tabanlı çözümleme (`RecipientResolutionService`) bu kanal için
    değil, Faz 4 AI kanalı için mevcuttur.
    """

    recipient_id: str = Field(description="Alıcı kullanıcı ID'si")
    artifact_kind: Literal["draft", "document"]
    source_artifact_id: str = Field(description="drafts.id veya evrak storage_path'i")
    #: Bir taslak için gönderim anında sabitlenir (bkz.
    #: `ArtifactTransferModel.source_version`'un kendi docstring'i); bir
    #: evrak için yok sayılır.
    source_version: Optional[int] = None
    #: İsteğe bağlı, çağıranın sağladığı idempotency belirteci -- aynı
    #: anahtarla tekrarlanan bir istek, yeniden çalıştırmak yerine
    #: özgün transferi döndürür.
    idempotency_key: Optional[str] = Field(default=None, max_length=200)


class GroupTransferSendRequest(BaseModel):
    """`POST /transfers/send-group` gövdesi -- yalnızca sohbet/REST üzerinden
    birden fazla alıcıya aynı anda dağıtım (Faz 5, #205). Bu isteğin
    AI kanalı karşılığı yoktur; bkz.
    `ArtifactTransferService.execute_group`'un kendi docstring'i.
    """

    recipient_ids: List[str] = Field(
        min_length=1,
        max_length=MAX_GROUP_TRANSFER_RECIPIENTS,
        description="Alıcı kullanıcı ID'leri",
    )
    artifact_kind: Literal["draft", "document"]
    source_artifact_id: str = Field(description="drafts.id veya evrak storage_path'i")
    source_version: Optional[int] = None
    #: O alıcının kendi idempotency anahtarını türetmek için her alıcı
    #: id'siyle birleştirilir -- bkz.
    #: `GroupTransferCommand.idempotency_key_prefix`.
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
