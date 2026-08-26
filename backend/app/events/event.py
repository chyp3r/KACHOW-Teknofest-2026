from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4
from pydantic import BaseModel, Field

class BaseEvent(BaseModel):
    """Domainler arasında gevşek bağlaşım sağlayan temel event yapısı."""
    event_id: str = Field(default_factory=lambda: str(uuid4()), description="Event'in benzersiz kimliği")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Event'in oluşma zamanı")
    event_type: str = Field(description="Event'in adı/türü")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event veri yükü")

class DocumentUploadedEvent(BaseEvent):
    event_type: str = "document.uploaded"

class DocumentClassifiedEvent(BaseEvent):
    event_type: str = "document.classified"

class DocumentAnalyzedEvent(BaseEvent):
    event_type: str = "document.analyzed"

class DraftCreatedEvent(BaseEvent):
    event_type: str = "draft.created"

class DraftSharedEvent(BaseEvent):
    """Bir `draft_shares` satırı oluşturuldu (`POST /drafts/{id}/send`).

    Toplu gönderim çağrısı başına değil, alıcı başına bir kez yayınlanır --
    nedeni için `DraftShareService.send`'in docstring'ine bakın. `payload`
    içinde `company_id`, `share_id`, `draft_id`, `sender_id`,
    `sender_username`, `recipient_id` taşınır; `app.events.subscribers`
    içindeki subscriber bunu `recipient_id` için bir `notifications`
    satırına ve canlı bir SSE bildirimine dönüştürür.
    """
    event_type: str = "draft.shared"

class DraftShareRespondedEvent(BaseEvent):
    """Bir alıcı paylaşılan taslağı kabul etti veya reddetti ("read" veya
    "withdrawn" durumları için asla yayınlanmaz -- bu ikisinin neden
    bildirim tetiklemediği için `DraftShareService`'in kendi docstring'ine
    bakın). `payload` içinde `company_id`, `share_id`, `draft_id`,
    `sender_id`, `recipient_id`, `recipient_username`,
    `status` ("accepted"|"rejected"), `response_note` taşınır.
    """
    event_type: str = "draft.share_responded"

class DocumentRoutedEvent(BaseEvent):
    event_type: str = "document.routed"

class ArtifactTransferredEvent(BaseEvent):
    """Bir `artifact_transfers` satırı oluşturuldu (`ArtifactTransferService.
    execute`, herhangi bir kanal). `payload` içinde `company_id`,
    `transfer_id`, `artifact_kind` ("draft"|"document"), `sender_id`,
    `sender_username`, `recipient_id`, `conversation_id` taşınır --
    `app.events.subscribers` içindeki subscriber bunu `recipient_id` için
    bir `notifications` satırına dönüştürür. Bilinçli olarak
    `body_preview`/içerik alanı yoktur: sıradan bir sohbet mesajının
    aksine, bir artifact transferinin kendi `conversation_messages` satırı
    (`kind="artifact"`) alıcının görmesi gereken her şeyi zaten taşır ve
    bildirimin yalnızca ona işaret etmesi yeterlidir -- kalıcı, geniş
    çapta okunan bir kaydın neden yalnızca katılım kısıtlı thread'e ait
    içeriği taşımaması gerektiği için `ConversationMessageCreatedEvent`'in
    kendi docstring'ine bakın.
    """
    event_type: str = "artifact.transferred"

class ConversationMessageCreatedEvent(BaseEvent):
    """Bir aktif alıcı için bir `conversation_messages` satırı oluşturuldu.

    Gönderen dışında her aktif (ayrılmamış) alıcı başına bir kez
    yayınlanır; bu, `DraftSharedEvent`'in çok alıcılı fan-out için zaten
    kullandığı aynı kuraldır (bkz. `app.domains.drafts.draft_share_service.
    DraftShareService.send`'in docstring'i) -- N üyeli bir grup mesajı,
    alıcı listesi taşıyan tek bir event yerine bunlardan N tane yayınlar.
    `payload` içinde `company_id`, `conversation_id`, `message_id`,
    `sender_id`, `sender_username`, `recipient_id`, `kind`
    ("text"|"artifact"), `body_preview` (kısaltılmış -- asla mesajın tam
    metni değil, nedeni için subscriber'ın kendi docstring'ine bakın)
    taşınır.
    """
    event_type: str = "messaging.message_created"

class UserCreatedEvent(BaseEvent):
    event_type: str = "user.created"

class UserDeletedEvent(BaseEvent):
    event_type: str = "user.deleted"

class UserPasswordChangedEvent(BaseEvent):
    event_type: str = "user.password_changed"
