import logging
from typing import List, Optional, Tuple
from uuid import uuid4

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.core.permissions.role_checker import bypasses_ownership
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.model.draft_share_model import DraftShareModel
from app.domains.drafts.repository import DraftRepository, DraftShareRepository
from app.domains.drafts.schema.draft_share_schema import DraftSendRequest
from app.domains.transfers.service import ArtifactTransferService, TransferCommand
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.events.event import DraftShareRespondedEvent
from app.events.event_bus import event_bus

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = ("sent", "read")


class DraftShareService:
    """Service for `draft_shares` -- the çalışanlar arası taslak gönder/al flow.

    `send` no longer performs the transfer itself -- it delegates the
    whole thing (authorize, policy, fork, delivery, audit, notification)
    to `ArtifactTransferService.execute(channel="rest")`, the single path
    every artifact transfer now goes through (see that service's own
    docstring). What's left here is purely the `draft_shares`-specific
    inbox/outbox/accept/reject bookkeeping this table's own consumers
    (`GET /drafts/inbox`, `/outbox`, the accept/reject/withdraw routes)
    still need -- it does not duplicate the ABAC/policy decision, only
    records that a share happened alongside the real transfer.

    Viewing/responding to an already-created share is *not* an ABAC
    decision: a `draft_shares` row's `recipient_id`/`sender_id` is itself
    the authorization (only the two parties, or ADMIN/MANAGER/ROOT
    company-wide via `bypasses_ownership`, may touch it) -- there is no
    `draft:read` check against the underlying `drafts` row here, which is
    deliberate: a recipient who does not own the draft and isn't
    ADMIN/MANAGER/ROOT would fail that check, yet must still be able to
    read what was sent to them. The share row (joined with the draft's
    content in every response -- see `DraftShareResponse`) is the access
    grant, not the draft's own ownership.
    """

    def __init__(
        self,
        share_repository: DraftShareRepository,
        draft_repository: DraftRepository,
        user_repository: UserRepository,
        transfer_service: ArtifactTransferService,
    ):
        self.share_repository = share_repository
        self.draft_repository = draft_repository
        self.user_repository = user_repository
        self.transfer_service = transfer_service

    @staticmethod
    async def _publish(event) -> None:
        """Publish a domain event without letting listener failures break the request.

        Same pattern as `app.domains.documents.service.DocumentService._publish`.
        """
        try:
            await event_bus.publish(event)
        except Exception:
            logger.exception("Failed to publish event %s", getattr(event, "event_type", "?"))

    async def send(
        self, draft_id: str, sender: UserModel, request: DraftSendRequest, company_id: str
    ) -> List[DraftShareModel]:
        """Send one draft version to one or more recipients.

        Each recipient goes through its own call to `ArtifactTransferService.
        execute` -- authorize, policy, fork, delivery, audit, and
        notification all happen there (see its own docstring). Unlike the
        old, single-implementation version of this method, a multi-
        recipient send is no longer strictly all-or-nothing: a transfer
        that already executed for an earlier recipient stays executed even
        if a later recipient's own policy check fails (self-send, inactive,
        insufficient clearance) -- unifying every channel onto one transfer
        path takes priority over preserving a batch-atomicity guarantee
        that only existed because no real transfer service existed yet.
        In practice this only matters for a genuinely multi-recipient send,
        which neither this endpoint's own frontend consumer (there isn't
        one) nor the new chat-composer send flow (single-recipient by
        construction) ever exercises.

        Raises:
            NotFoundException: If `draft_id` doesn't resolve within
                `company_id`, or (from `ArtifactTransferService.execute`)
                a `recipient_ids` entry doesn't.
            AuthorizationException: If `sender` isn't allowed to send this
                specific draft, or `TransferPolicy` denies for a narrower
                reason (self-send, inactive recipient).
        """
        draft = await self.draft_repository.get_by_id(draft_id)
        if draft is None:
            raise NotFoundException(message="Taslak bulunamadı.")

        shares: List[DraftShareModel] = []
        for recipient_id in request.recipient_ids:
            await self.transfer_service.execute(
                TransferCommand(
                    company_id=company_id,
                    sender=sender,
                    recipient_id=recipient_id,
                    artifact_kind="draft",
                    source_artifact_id=draft.id,
                    source_version=draft.version,
                    channel="rest",
                )
            )
            share = await self.share_repository.create(
                DraftShareModel(
                    id=uuid4().hex,
                    company_id=company_id,
                    draft_id=draft.id,
                    sender_id=sender.id,
                    recipient_id=recipient_id,
                    # Already resolved once at draft-write time (see
                    # `drafts.destination_unit_id`'s own docstring) --
                    # no per-send name lookup needed anymore.
                    suggested_unit_id=draft.destination_unit_id,
                    message=request.message,
                    status="sent",
                )
            )
            shares.append(share)
        return shares

    async def list_inbox(
        self, company_id: str, user_id: str, status: Optional[str], skip: int, limit: int
    ) -> Tuple[List[Tuple[DraftShareModel, DraftModel]], int]:
        items = await self.share_repository.list_inbox(
            company_id, user_id, status=status, skip=skip, limit=limit
        )
        total = await self.share_repository.count_inbox(company_id, user_id, status=status)
        return items, total

    async def list_outbox(
        self, company_id: str, user_id: str, status: Optional[str], skip: int, limit: int
    ) -> Tuple[List[Tuple[DraftShareModel, DraftModel]], int]:
        items = await self.share_repository.list_outbox(
            company_id, user_id, status=status, skip=skip, limit=limit
        )
        total = await self.share_repository.count_outbox(company_id, user_id, status=status)
        return items, total

    async def _get_owned_share(
        self, share_id: str, company_id: str, requester: UserModel
    ) -> Tuple[DraftShareModel, DraftModel]:
        share = await self.share_repository.get_by_id(share_id, company_id)
        if share is None:
            raise NotFoundException(message="Paylaşım bulunamadı.")
        if (
            requester.id not in (share.sender_id, share.recipient_id)
            and not bypasses_ownership(requester)
        ):
            raise AuthorizationException(message="Bu paylaşıma erişim izniniz yok.")
        draft = await self.draft_repository.get_by_id(share.draft_id)
        return share, draft

    async def mark_read(
        self, share_id: str, company_id: str, requester: UserModel
    ) -> Tuple[DraftShareModel, DraftModel]:
        share, draft = await self._get_owned_share(share_id, company_id, requester)
        if share.recipient_id != requester.id:
            raise AuthorizationException(message="Yalnızca alıcı okundu olarak işaretleyebilir.")
        share = await self.share_repository.mark_read(share)
        return share, draft

    async def respond(
        self, share_id: str, company_id: str, requester: UserModel, status: str, response_note: Optional[str]
    ) -> Tuple[DraftShareModel, DraftModel]:
        """Accept or reject a share addressed to `requester`.

        Purely a status transition now -- no longer forks a draft version.
        The recipient already got their own, immediately-owned copy at
        *send* time (`ArtifactTransferService.execute`'s draft fork, see
        its own docstring), so accepting a share is just acknowledging
        delivery, the same way `mark_read` already is. Forking again here
        on top of that would have produced a second, orphaned copy the
        recipient never asked for -- the exact double-fork this change
        removes (see the plan's own §D5).

        Raises:
            NotFoundException: If `share_id` doesn't resolve.
            AuthorizationException: If `requester` isn't the share's
                `recipient_id`, or the share isn't `sent`/`read` anymore
                (already resolved, or withdrawn).
        """
        share, draft = await self._get_owned_share(share_id, company_id, requester)
        if share.recipient_id != requester.id:
            raise AuthorizationException(message="Yalnızca alıcı yanıt verebilir.")
        if share.status not in _ACTIVE_STATUSES:
            raise AuthorizationException(message="Bu paylaşım zaten yanıtlanmış veya geri çekilmiş.")

        share = await self.share_repository.respond(share, status, response_note)

        await self._publish(
            DraftShareRespondedEvent(
                payload={
                    "company_id": company_id,
                    "share_id": share.id,
                    "draft_id": share.draft_id,
                    "sender_id": share.sender_id,
                    "recipient_id": share.recipient_id,
                    "recipient_username": requester.username,
                    "status": status,
                    "response_note": response_note,
                }
            )
        )
        return share, draft

    async def withdraw(self, share_id: str, company_id: str, requester: UserModel) -> DraftShareModel:
        share, _draft = await self._get_owned_share(share_id, company_id, requester)
        if share.sender_id != requester.id and not bypasses_ownership(requester):
            raise AuthorizationException(message="Yalnızca gönderen geri çekebilir.")
        if share.status != "sent":
            raise AuthorizationException(message="Yalnızca 'sent' durumundaki bir paylaşım geri çekilebilir.")
        return await self.share_repository.withdraw(share)
