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

#: Tembel (lazy) olarak oluşturulan her kişisel varsayılan havuzun aldığı
#: etiket -- bkz. `DocumentPoolRepository.get_or_create_default`.
_PERSONAL_POOL_NAME = "Kişisel Havuz"


class PoolService:
    """Evrak havuzu (document pool) iş kurallarını yürüten servis.

    Buradaki yetkilendirme, Faz 2 ABAC motoru (`app.core.authz`) var
    olmadan önce kod tabanının geri kalanının kullandığı aynı
    `bypasses_ownership` kuralını izler -- havuzlar polimorfik bir
    kaynaktır (`owner_type` "user"|"unit"|"company"), bu da o motorun
    tek-sahipli `Resource` biçimine daha büyük bir genişleme olmadan
    temiz biçimde eşlenmez; makul bir sonraki adım, ama bu özelliğin
    bugün doğru olması için gerekli değil.
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
        """Bir havuzun kendi sahibi her zaman görüntüleyebilir; aksi
        takdirde ADMIN/MANAGER/ROOT (şirket geneli, belge sahipliğiyle
        aynı -- bkz. `bypasses_ownership`)."""
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
        """`document`'ı `recipient`'ın kişisel havuzuna, yetkilerine saygı
        göstererek push eder.

        `hizmete_ozel` bir çalışana push edilen `gizli` bir belge *özel
        olarak o alıcı için* reddedilir -- beş kişiye push edip
        görmemesi gereken kişi için sessizce başarılı olması, sistemin
        geri kalanının zaten uyguladığı gizlilik merdivenini bozardı;
        kısmi bir sonuç, çağıranın tek bir hep-ya-da-hiç hatası yerine
        tam olarak kimin atlandığını ve nedenini görmesini sağlar.
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
        """`document`'ı bir artifact transferi olarak `recipient`'ın
        kişisel havuzuna dosyalar, mevcut metadata'sını `metadata_snapshot`
        içine dondurur (nedeni için `DocumentPoolItemModel`'in kendi
        docstring'ine bakın -- paylaşılan blob asla mutasyona uğramaz,
        ama bu satırın metadata kopyası, gönderen kaynağı sonradan
        düzenlerse alıcının görünümünü sabit tutan şeydir).

        Yalnızca `app.domains.transfers.ArtifactTransferService.execute`
        tarafından çağrılır -- yetki, bu çalışmadan önce zaten
        `TransferPolicy` tarafından kontrol edilmiştir, toplu-push akışı
        için `_push_one`'ın kendi satır-içi kontrolünden farklı olarak,
        bu yüzden bu metot çağıranına güvenir ve yeniden kontrol etmez.

        Zaten transfer edilmiş bir belgeyi yeniden dosyalamak (aynı
        alıcıya, aynı veya farklı bir gönderen tarafından tekrar
        gönderilmiş), `UNIQUE(pool_id, document_id)`'ye çarpmak yerine
        mevcut öğenin snapshot'ını ve `transferred_by`'ını yerinde
        tazeler -- alıcının bir kopyası vardır ve bu en son transferi
        yansıtır.
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
        """Tek bir belgeyi birden çok alıcının (veya bir birimin tamamının)
        kişisel havuzlarına toplu push eder.

        Args:
            request: `recipient_ids` veya `unit_id`, şemanın kendisi
                tarafından karşılıklı dışlayıcı olarak doğrulanır.
            sender: Push eden Admin/Manager (router'da rol ile kilitlenir).
            company_id: Aşağıdaki her sorguyu kapsamlar.
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
        """Tek bir belgeyi doğrudan belirli, önceden bilinen bir havuza
        push eder."""
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
