import logging
from typing import List, Optional, Tuple
from uuid import uuid4

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.core.authz.attributes import Action, Resource
from app.core.authz.dependency import subject_from_user
from app.core.authz.engine import authorize
from app.core.permissions.role_checker import bypasses_ownership
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.model.draft_share_model import DraftShareModel
from app.domains.drafts.repository import DraftRepository, DraftShareRepository
from app.domains.drafts.schema.draft_share_schema import DraftSendRequest
from app.domains.quotas.service import DRAFTS_METRIC, QuotaService
from app.domains.units.repository import UnitRepository
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.events.event import DraftSharedEvent, DraftShareRespondedEvent
from app.events.event_bus import event_bus

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = ("sent", "read")


class DraftShareService:
    """Service for `draft_shares` -- the çalışanlar arası taslak gönder/al flow.

    Unlike `PoolService` (a deliberately-scoped `bypasses_ownership` check,
    see its own docstring for why), sending itself goes through the real
    ABAC engine (`Action.DRAFT_SEND`, already defined and unused since Faz
    2) since a draft has exactly one owner and maps cleanly onto
    `engine.authorize`'s `Resource` shape -- there was no reason to take
    the same shortcut twice.

    Viewing/responding to an already-created share, though, is *not* an
    ABAC decision: a `draft_shares` row's `recipient_id`/`sender_id` is
    itself the authorization (only the two parties, or ADMIN/MANAGER/ROOT
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
        unit_repository: UnitRepository,
        quota_service: Optional[QuotaService] = None,
    ):
        self.share_repository = share_repository
        self.draft_repository = draft_repository
        self.user_repository = user_repository
        self.unit_repository = unit_repository
        self.quota_service = quota_service

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

        Validates every recipient belongs to `company_id` and exists before
        creating any share (all-or-nothing -- unlike `PoolService.push`'s
        deliberate partial-success design, a bad recipient id here is a
        client error to reject outright, not an expected per-recipient
        business outcome like a clearance mismatch).

        Raises:
            NotFoundException: If `draft_id`, or any `recipient_ids` entry,
                doesn't resolve within `company_id`.
            AuthorizationException: If `sender` isn't allowed to send this
                specific draft (`Action.DRAFT_SEND` -- EMPLOYEE only its
                own, ADMIN/MANAGER/ROOT company-wide).
        """
        draft = await self.draft_repository.get_by_id(draft_id)
        if draft is None:
            raise NotFoundException(message="Taslak bulunamadı.")

        resource = Resource(
            type="draft", id=draft.id, company_id=draft.company_id, owner_id=draft.user_id
        )
        decision = authorize(subject_from_user(sender), Action.DRAFT_SEND, resource)
        if not decision.permit:
            raise AuthorizationException(message="Bu taslağı gönderme izniniz yok.")

        recipients: List[UserModel] = []
        for recipient_id in request.recipient_ids:
            recipient = await self.user_repository.get_by_id_in_company(recipient_id, company_id)
            if recipient is None:
                raise NotFoundException(message=f"Kullanıcı bulunamadı: {recipient_id}")
            recipients.append(recipient)

        suggested_unit_id: Optional[str] = None
        if draft.destination:
            unit = await self.unit_repository.get_by_name(draft.destination, company_id)
            if unit is not None:
                suggested_unit_id = unit.id

        shares: List[DraftShareModel] = []
        for recipient in recipients:
            share = await self.share_repository.create(
                DraftShareModel(
                    id=uuid4().hex,
                    company_id=company_id,
                    draft_id=draft.id,
                    sender_id=sender.id,
                    recipient_id=recipient.id,
                    suggested_unit_id=suggested_unit_id,
                    message=request.message,
                    status="sent",
                )
            )
            shares.append(share)
            await self._publish(
                DraftSharedEvent(
                    payload={
                        "company_id": company_id,
                        "share_id": share.id,
                        "draft_id": draft.id,
                        "sender_id": sender.id,
                        "sender_username": sender.username,
                        "recipient_id": recipient.id,
                    }
                )
            )
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

        An `accepted` share forks a new version of the draft -- owned by the
        recipient, chained to the original via `parent_draft_id` -- through
        the same `DraftRepository.create_version` every other revision uses
        (see its own docstring): "accepting" a taslak means taking it over
        to continue working on it, which only means something if the
        recipient actually ends up owning a row they can act on afterwards
        (`GET /drafts/{new_id}`, further edits, ...). A `rejected` share
        forks nothing.

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

        if status == "accepted" and draft is not None:
            # Accepting forks a real new draft row owned by `requester` --
            # counts against their own company's draft quota exactly like
            # any other new draft, see `QuotaService`'s module docstring.
            if self.quota_service is not None:
                await self.quota_service.check_and_increment(company_id, DRAFTS_METRIC)
            await self.draft_repository.create_version(
                user_id=requester.id,
                company_id=company_id,
                session_id=None,
                document_id=draft.document_id,
                content=draft.content,
                parent=draft,
                correspondence_type=draft.correspondence_type,
                destination=draft.destination,
            )

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
