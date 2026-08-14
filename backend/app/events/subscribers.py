"""Registers listeners on the process-wide event bus.

``DocumentService``/``DraftService`` already publish ``DocumentUploadedEvent``
and ``DocumentAnalyzedEvent``, but nothing ever subscribed to them -- the bus
was write-only. Importing this module (see ``app.lifespan``) registers the
first listener so those publishes have an effect.
"""

import logging

from app.domains.notifications.repository import NotificationRepository
from app.domains.notifications.service import NotificationService
from app.events.event import DocumentAnalyzedEvent, DraftSharedEvent, DraftShareRespondedEvent
from app.events.subscriber import subscribe
from app.infrastructure.cache import get_cache
from app.infrastructure.database.session import tenant_session

logger = logging.getLogger(__name__)


@subscribe("document.analyzed")
async def _log_document_analyzed(event: DocumentAnalyzedEvent) -> None:
    """Structured log line for every completed Görev 1 analysis.

    A stand-in for a real downstream consumer (a search index, an audit
    trail, a Prometheus counter labelled by document_type) -- the point here
    is that the event now reaches at least one listener, not what that
    listener does.
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
    """Shared body for both draft-share listeners below: open a tenant-scoped
    session (there is no request in flight here to read GUCs from -- see
    ``tenant_session``'s own docstring), write the notification row, and
    best-effort publish it live.

    A listener raising would only ever be logged by ``EventBus.
    _safe_execute_async`` and silently swallowed (see its docstring) -- so a
    failure here costs the live push and the row, not the request that
    triggered the event; the caller (``DraftShareService``) already
    committed the share itself before publishing, so this failing never
    rolls back the action the user actually asked for.
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
    """A taslak was sent to someone -- notify the recipient."""
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
    """A recipient accepted/rejected a shared taslak -- notify the sender."""
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
