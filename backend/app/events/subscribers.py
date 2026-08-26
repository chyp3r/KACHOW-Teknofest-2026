"""Süreç genelindeki event bus'a listener kaydeder.

``DocumentService``/``DraftService`` zaten ``DocumentUploadedEvent`` ve
``DocumentAnalyzedEvent`` yayınlıyordu, ancak bunlara hiçbir zaman abone
olunmamıştı -- bus yalnızca yazma amaçlıydı. Bu modülün import edilmesi
(bkz. ``app.lifespan``) ilk listener'ı kaydeder, böylece bu yayınların bir
etkisi olur.
"""

import logging

from app.domains.notifications.repository import NotificationRepository
from app.domains.notifications.service import NotificationService
from app.events.event import (
    ArtifactTransferredEvent,
    ConversationMessageCreatedEvent,
    DocumentAnalyzedEvent,
    DraftSharedEvent,
    DraftShareRespondedEvent,
)
from app.events.subscriber import subscribe
from app.infrastructure.cache import get_cache
from app.infrastructure.database.session import tenant_session

logger = logging.getLogger(__name__)


@subscribe("document.analyzed")
async def _log_document_analyzed(event: DocumentAnalyzedEvent) -> None:
    """Tamamlanan her Görev 1 analizi için yapılandırılmış log satırı.

    Gerçek bir downstream tüketicisi (bir arama indeksi, bir denetim izi,
    document_type'a göre etiketlenmiş bir Prometheus sayacı) için bir
    yer tutucu -- buradaki asıl nokta, event'in artık en az bir listener'a
    ulaşması, o listener'ın ne yaptığı değil.
    """
    logger.info(
        "document_analyzed",
        extra={
            "file_name": event.payload.get("file_name"),
            "document_type": event.payload.get("document_type"),
            "compliance_status": event.payload.get("compliance_status"),
            "missing_field_count": event.payload.get("missing_field_count"),
        },
    )


async def _write_notification(
    *,
    company_id: str,
    user_id: str,
    type: str,
    title: str,
    body: str,
    resource_type: str,
    resource_id: str,
) -> None:
    """Aşağıdaki iki draft-share listener'ı için ortak gövde: tenant kapsamlı
    bir session açar (burada GUC'ları okuyacak bir istek akışta değildir --
    bkz. ``tenant_session``'ın kendi docstring'i), bildirim satırını yazar
    ve best-effort şekilde canlı olarak yayınlar.

    Bir listener'ın exception fırlatması yalnızca ``EventBus.
    _safe_execute_async`` tarafından loglanır ve sessizce yutulur (bkz. onun
    docstring'i) -- yani buradaki bir hata, event'i tetikleyen isteği değil,
    yalnızca canlı bildirim ve satırı kaybettirir; çağıran
    (``DraftShareService``) yayınlamadan önce paylaşımı zaten commit etmiş
    olduğundan, buradaki bir başarısızlık kullanıcının asıl istediği
    eylemi asla geri almaz.
    """
    async with tenant_session(company_id) as session:
        service = NotificationService(NotificationRepository(session), cache=get_cache())
        await service.create(
            company_id=company_id,
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            resource_type=resource_type,
            resource_id=resource_id,
        )


@subscribe("draft.shared")
async def _notify_draft_shared(event: DraftSharedEvent) -> None:
    """Bir taslak birisine gönderildi -- alıcıyı bilgilendir."""
    sender_username = event.payload.get("sender_username", "Bir kullanıcı")
    await _write_notification(
        company_id=event.payload["company_id"],
        user_id=event.payload["recipient_id"],
        type="draft_shared",
        title="Yeni bir taslak paylaşıldı",
        body=f"{sender_username} size bir taslak gönderdi.",
        resource_type="draft_share",
        resource_id=event.payload["share_id"],
    )


@subscribe("draft.share_responded")
async def _notify_draft_share_responded(event: DraftShareRespondedEvent) -> None:
    """Bir alıcı paylaşılan taslağı kabul etti/reddetti -- göndereni bilgilendir."""
    recipient_username = event.payload.get("recipient_username", "Alıcı")
    status = event.payload["status"]
    verb = "kabul etti" if status == "accepted" else "reddetti"
    await _write_notification(
        company_id=event.payload["company_id"],
        user_id=event.payload["sender_id"],
        type="draft_share_responded",
        title="Taslağınıza yanıt verildi",
        body=f"{recipient_username} gönderdiğiniz taslağı {verb}.",
        resource_type="draft_share",
        resource_id=event.payload["share_id"],
    )


@subscribe("messaging.message_created")
async def _notify_new_message(event: ConversationMessageCreatedEvent) -> None:
    """Bir sohbet mesajı gönderildi -- bir aktif alıcıyı bilgilendir.

    Her aktif alıcı başına bir kez yayınlanır (bkz.
    `ConversationMessageCreatedEvent`'in kendi docstring'i), bu yüzden bu
    fonksiyon `_notify_draft_shared` ile aynı şekilde alıcı başına bir kez
    tetiklenir. Buradaki `body`, mesajın tamamı değil
    `payload["body_preview"]`'dir -- bir bildirim satırı kalıcı, geniş
    çapta okunan bir kayıttır (`GET /notifications`); sohbetin tam içeriği
    `conversation_messages`'ta kalır ve yalnızca katılım kısıtlı
    `GET /messaging/conversations/{id}/messages` üzerinden okunur.
    """
    sender_username = event.payload.get("sender_username", "Bir kullanıcı")
    preview = event.payload.get("body_preview", "")
    await _write_notification(
        company_id=event.payload["company_id"],
        user_id=event.payload["recipient_id"],
        type="conversation_message",
        title=f"{sender_username} size bir mesaj gönderdi",
        body=preview,
        resource_type="conversation",
        resource_id=event.payload["conversation_id"],
    )


@subscribe("artifact.transferred")
async def _notify_artifact_transferred(event: ArtifactTransferredEvent) -> None:
    """Bir artifact (taslak/evrak) transfer edildi -- alıcıyı bilgilendir.

    Sabit bir Türkçe cümle dışında `body` yok -- artifact'ın kendi
    başlığı/içeriği transfer satırında ve sohbetin `kind="artifact"`
    mesajında yaşar, asla bir bildirime kopyalanmaz (bkz.
    `ArtifactTransferredEvent`'in kendi docstring'i).
    """
    sender_username = event.payload.get("sender_username", "Bir kullanıcı")
    kind_label = "bir taslak" if event.payload.get("artifact_kind") == "draft" else "bir evrak"
    await _write_notification(
        company_id=event.payload["company_id"],
        user_id=event.payload["recipient_id"],
        type="artifact_transferred",
        title="Yeni bir gönderiniz var",
        body=f"{sender_username} size {kind_label} gönderdi.",
        resource_type="conversation",
        resource_id=event.payload["conversation_id"],
    )
