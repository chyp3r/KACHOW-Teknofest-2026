import logging
from typing import List, Optional, Tuple
from uuid import uuid4

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.core.enums.sensitivity_level import SensitivityLevel
from app.core.permissions.role_checker import assert_clearance, bypasses_ownership
from app.domains.documents.model.document_model import DocumentModel
from app.domains.documents.repository import DocumentRepository
from app.domains.pools.model.document_pool_item_model import DocumentPoolItemModel
from app.domains.pools.model.document_pool_model import DocumentPoolModel
from app.domains.pools.repository import DocumentPoolItemRepository, DocumentPoolRepository
from app.domains.pools.schema.pool_schema import PoolPushRequest, PoolPushResultItem
from app.domains.units.repository import UnitMembershipRepository, UnitRepository
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository

logger = logging.getLogger(__name__)

#: The label every lazily-created personal default pool gets -- see
#: `DocumentPoolRepository.get_or_create_default`.
_PERSONAL_POOL_NAME = "Kişisel Havuz"


class PoolService:
    """Service executing evrak havuzu (document pool) business rules.

    Authorization here follows the same `bypasses_ownership` convention the
    rest of the codebase used before the Faz 2 ABAC engine existed
    (`app.core.authz`) -- pools are a polymorphic resource (`owner_type`
    "user"|"unit"|"company"), which doesn't map cleanly onto that engine's
    single-owner `Resource` shape without a larger extension; a reasonable
    follow-up, not required for this feature to be correct today.
    """

    def __init__(
        self,
        pool_repository: DocumentPoolRepository,
        item_repository: DocumentPoolItemRepository,
        document_repository: DocumentRepository,
        user_repository: UserRepository,
        unit_membership_repository: UnitMembershipRepository,
    ):
        self.pool_repository = pool_repository
        self.item_repository = item_repository
        self.document_repository = document_repository
        self.user_repository = user_repository
        self.unit_membership_repository = unit_membership_repository

    async def get_or_create_personal_pool(self, user_id: str, company_id: str) -> DocumentPoolModel:
        return await self.pool_repository.get_or_create_default(
            "user", user_id, company_id, name=_PERSONAL_POOL_NAME
        )

    def _assert_can_view_pool(self, pool: DocumentPoolModel, requester: UserModel) -> None:
        """A pool's own owner may always view it; otherwise ADMIN/MANAGER/ROOT
        (company-wide, same as document ownership -- see `bypasses_ownership`)."""
        if pool.owner_type == "user" and pool.owner_id == requester.id:
            return
        if bypasses_ownership(requester):
            return
        raise AuthorizationException(message="Bu havuza erişim izniniz yok.")

    async def list_pool_items(
        self, pool_id: str, company_id: str, requester: UserModel, skip: int = 0, limit: int = 100
    ) -> Tuple[List[Tuple[DocumentPoolItemModel, DocumentModel]], int]:
        pool = await self.pool_repository.get_by_id(pool_id, company_id)
        if pool is None:
            raise NotFoundException(message="Havuz bulunamadı.")
        self._assert_can_view_pool(pool, requester)

        items = await self.item_repository.list_for_pool(pool_id, company_id, skip=skip, limit=limit)
        total = await self.item_repository.count_for_pool(pool_id, company_id)
        return items, total

    async def _push_one(
        self,
        *,
        document: DocumentModel,
        recipient: UserModel,
        added_by: str,
        note: Optional[str],
        company_id: str,
    ) -> PoolPushResultItem:
        """Push `document` into `recipient`'s personal pool, honoring their clearance.

        A `gizli` document pushed at a `hizmete_ozel` employee is refused
        *for that recipient specifically* -- pushing to five people and
        having it silently succeed for the one who shouldn't see it would
        defeat the confidentiality ladder the rest of the system already
        enforces; a partial result lets the caller see exactly who was
        skipped and why, rather than a single all-or-nothing failure.
        """
        try:
            try:
                document_level = SensitivityLevel(document.sensitivity_level)
            except ValueError:
                document_level = SensitivityLevel.UNMARKED
            assert_clearance(recipient, document_level)
        except AuthorizationException:
            return PoolPushResultItem(
                user_id=recipient.id,
                status="denied_clearance",
                reason="Alıcının gizlilik yetkisi bu evrak için yeterli değil.",
            )

        pool = await self.get_or_create_personal_pool(recipient.id, company_id)
        if await self.item_repository.exists(pool.id, document.id):
            return PoolPushResultItem(user_id=recipient.id, status="pushed")

        await self.item_repository.create(
            DocumentPoolItemModel(
                id=uuid4().hex,
                company_id=company_id,
                pool_id=pool.id,
                document_id=document.id,
                added_by=added_by,
                source="manager_push",
                note=note,
            )
        )
        return PoolPushResultItem(user_id=recipient.id, status="pushed")

    async def file_transferred_document(
        self, *, document: DocumentModel, recipient: UserModel, sender: UserModel, company_id: str
    ) -> DocumentPoolItemModel:
        """File `document` into `recipient`'s personal pool as an artifact
        transfer, freezing its current metadata into `metadata_snapshot`
        (see `DocumentPoolItemModel`'s own docstring for why -- the shared
        blob is never mutated, but this row's metadata copy is what keeps
        the recipient's view stable if the sender edits the source
        afterward).

        Called only by `app.domains.transfers.ArtifactTransferService.
        execute` -- clearance is already checked by `TransferPolicy`
        before this runs, unlike `_push_one`'s own inline check for the
        bulk-push flow, so this method trusts its caller and does not
        re-check it.

        Re-filing an already-transferred document (sent to the same
        recipient again, by the same or a different sender) refreshes the
        existing item's snapshot and `transferred_by` in place rather than
        hitting `UNIQUE(pool_id, document_id)` -- the recipient has one
        copy, and it reflects the latest transfer.
        """
        pool = await self.get_or_create_personal_pool(recipient.id, company_id)
        snapshot = {
            "document_type": document.document_type,
            "document_type_label": document.document_type_label,
            "compliance_status": document.compliance_status,
            "summary": document.summary,
            "sensitivity_level": document.sensitivity_level,
            "pii_flagged": document.pii_flagged,
        }
        existing = await self.item_repository.get_by_pool_and_document(pool.id, document.id)
        if existing is not None:
            existing.metadata_snapshot = snapshot
            existing.transferred_by = sender.id
            existing.source = "transfer"
            return await self.item_repository.save(existing)

        return await self.item_repository.create(
            DocumentPoolItemModel(
                id=uuid4().hex,
                company_id=company_id,
                pool_id=pool.id,
                document_id=document.id,
                added_by=sender.id,
                source="transfer",
                transferred_by=sender.id,
                metadata_snapshot=snapshot,
            )
        )

    async def push(
        self, request: PoolPushRequest, sender: UserModel, company_id: str
    ) -> List[PoolPushResultItem]:
        """Bulk-push one document into several recipients' (or a whole unit's) personal pools.

        Args:
            request: `recipient_ids` or `unit_id`, validated mutually
                exclusive by the schema itself.
            sender: The Admin/Manager pushing (role-gated at the router).
            company_id: Scopes every lookup below.
        """
        document = await self.document_repository.get_by_id(request.document_id, company_id)
        if document is None:
            raise NotFoundException(message="Evrak bulunamadı.")

        if request.unit_id is not None:
            members = await self.unit_membership_repository.list_for_unit(request.unit_id, company_id)
            recipient_ids = [user.id for _membership, user in members]
        else:
            recipient_ids = request.recipient_ids or []

        results: List[PoolPushResultItem] = []
        for user_id in recipient_ids:
            recipient = await self.user_repository.get_by_id_in_company(user_id, company_id)
            if recipient is None:
                results.append(
                    PoolPushResultItem(user_id=user_id, status="not_found", reason="Kullanıcı bulunamadı.")
                )
                continue
            results.append(
                await self._push_one(
                    document=document,
                    recipient=recipient,
                    added_by=sender.id,
                    note=request.note,
                    company_id=company_id,
                )
            )
        return results

    async def push_to_pool(
        self, pool_id: str, document_id: str, note: Optional[str], sender: UserModel, company_id: str
    ) -> DocumentPoolItemModel:
        """Push one document directly into a specific, already-known pool."""
        pool = await self.pool_repository.get_by_id(pool_id, company_id)
        if pool is None:
            raise NotFoundException(message="Havuz bulunamadı.")
        document = await self.document_repository.get_by_id(document_id, company_id)
        if document is None:
            raise NotFoundException(message="Evrak bulunamadı.")

        if pool.owner_type == "user":
            recipient = await self.user_repository.get_by_id_in_company(pool.owner_id, company_id)
            if recipient is not None:
                try:
                    document_level = SensitivityLevel(document.sensitivity_level)
                except ValueError:
                    document_level = SensitivityLevel.UNMARKED
                assert_clearance(recipient, document_level)

        if await self.item_repository.exists(pool.id, document.id):
            raise AuthorizationException(message="Bu evrak zaten bu havuzda.")

        return await self.item_repository.create(
            DocumentPoolItemModel(
                id=uuid4().hex,
                company_id=company_id,
                pool_id=pool.id,
                document_id=document.id,
                added_by=sender.id,
                source="manager_push",
                note=note,
            )
        )

    async def remove_item(self, pool_id: str, item_id: str, company_id: str, requester: UserModel) -> None:
        pool = await self.pool_repository.get_by_id(pool_id, company_id)
        if pool is None:
            raise NotFoundException(message="Havuz bulunamadı.")
        self._assert_can_view_pool(pool, requester)

        item = await self.item_repository.get_by_id(item_id, company_id)
        if item is None or item.pool_id != pool_id:
            raise NotFoundException(message="Havuz öğesi bulunamadı.")

        deleted = await self.item_repository.delete(item_id, company_id)
        if not deleted:
            raise NotFoundException(message="Havuz öğesi bulunamadı.")

    async def acknowledge_item(self, item_id: str, company_id: str, requester: UserModel) -> DocumentPoolItemModel:
        item = await self.item_repository.get_by_id(item_id, company_id)
        if item is None:
            raise NotFoundException(message="Havuz öğesi bulunamadı.")

        pool = await self.pool_repository.get_by_id(item.pool_id, company_id)
        if pool is None:
            raise NotFoundException(message="Havuz öğesi bulunamadı.")
        self._assert_can_view_pool(pool, requester)

        acknowledged = await self.item_repository.acknowledge(item_id, company_id)
        if acknowledged is None:
            raise NotFoundException(message="Havuz öğesi bulunamadı.")
        return acknowledged
