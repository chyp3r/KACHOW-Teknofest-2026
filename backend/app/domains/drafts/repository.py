from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.model.draft_share_model import DraftShareModel


class DraftRepository:
    """`drafts` tablosunun arkasındaki versiyon-zinciri kayıt defteri (bkz. `DraftModel`)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, draft_id: str) -> Optional[DraftModel]:
        result = await self.db.execute(
            select(DraftModel).where(DraftModel.id == draft_id, DraftModel.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def get_latest_for_session(self, session_id: str) -> Optional[DraftModel]:
        """Bir oturum için en son versiyon -- "geçerli taslak"."""
        result = await self.db.execute(
            select(DraftModel)
            .where(DraftModel.session_id == session_id, DraftModel.is_deleted.is_(False))
            .order_by(DraftModel.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def attach_session(self, draft: DraftModel, session_id: str) -> DraftModel:
        """Daha önce oturumsuz olan bir taslağı, ilk revizyon chat'ine bağla."""
        if draft.session_id is not None:
            return draft
        draft.session_id = session_id
        await self.db.flush()
        return draft

    async def list_versions_for_session(self, session_id: str) -> List[DraftModel]:
        """Bir oturuma ait tüm versiyonlar, en eskiden en yeniye."""
        result = await self.db.execute(
            select(DraftModel)
            .where(DraftModel.session_id == session_id, DraftModel.is_deleted.is_(False))
            .order_by(DraftModel.version.asc())
        )
        return list(result.scalars().all())

    def _latest_version_query(
        self,
        company_id: Optional[str],
        session_id: Optional[str],
        document_id: Optional[str],
        user_id: Optional[str],
    ):
        """Filtrelenmiş, sıralama/sayfalama uygulanmamış "birleştirilmiş zincir
        başına bir satır" sorgusu -- `list_drafts` (bunun üzerine
        `order_by`/`offset`/`limit` ekler) ve `count_drafts` (bunu her
        satırı çekip `len()` almak yerine `SELECT count()` içine sarar)
        tarafından paylaşılır."""
        group_key = func.coalesce(DraftModel.session_id, DraftModel.id)
        latest_version = (
            select(
                group_key.label("group_key"),
                func.max(DraftModel.version).label("max_version"),
            )
            .where(DraftModel.is_deleted.is_(False))
            .group_by(group_key)
            .subquery()
        )
        query = select(DraftModel).join(
            latest_version,
            (group_key == latest_version.c.group_key)
            & (DraftModel.version == latest_version.c.max_version),
        )
        if company_id is not None:
            query = query.where(DraftModel.company_id == company_id)
        if session_id is not None:
            query = query.where(DraftModel.session_id == session_id)
        if document_id is not None:
            query = query.where(DraftModel.document_id == document_id)
        if user_id is not None:
            query = query.where(DraftModel.user_id == user_id)
        return query

    async def list_drafts(
        self,
        company_id: Optional[str] = None,
        session_id: Optional[str] = None,
        document_id: Optional[str] = None,
        user_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[DraftModel]:
        """Taslakları oturum başına bir satır olarak listele -- yalnızca her
        oturumun en son versiyonu.

        `DocumentRepository.count_for_owner`'ın listele-sonra-`len()`-al
        yaklaşımı yerine, `session_id` başına `max(version)` alt sorgusuna
        karşı bir self-join olarak kuruldu; çünkü bir taslak listelemesi
        zaten her oturumun versiyon zincirini tek bir satıra indirgemek
        zorundadır ve bir alt sorgu join'i bunu her versiyonu çekmek yerine
        tek bir sorguda yapar.

        Gruplama anahtarı yalın `session_id` değil, `COALESCE(session_id,
        id)`'dir. Doğrudan bir `POST /documents/draft` çağrısı (hiç chat
        oturumu yok -- bkz. `DraftModel.session_id`'in docstring'i)
        `session_id`'yi `NULL` bırakır ve SQL'in üç değerli mantığı `NULL =
        NULL`'u `TRUE` değil `NULL` olarak değerlendirir: yalın bir
        `session_id == session_id` join koşulu bu tür *her* taslağı bu
        listeden sessizce düşürürdü, ve yalın `session_id`'ye göre
        gruplamak da (join koşulunun aksine `NULL`'ları gerçekten bir arada
        kovalayan `GROUP BY` üzerinden) sistemdeki tüm ilgisiz oturumsuz
        taslakları tek bir ortak "en son versiyon"a birleştirirdi --
        bunlardan herhangi biri `version=1`'i aştığı anda (ki bu yalnızca
        `DraftShareService.respond`'un kabul-fork'u bir tane
        üretebildiğinden beri mümkün) sistem genelinde tek, baskın bir
        satır dışında hepsini gizlerdi. `session_id` `NULL` olduğunda
        satırın kendi `id`'sine geri dönmek, bunun yerine her oturumsuz
        taslağa kendi tekil grubunu verir: hem yaygın durum için doğrudur
        (birbirine hiç birleşmemesi gereken bağımsız doğrudan taslaklar),
        hem de özellikle kabul edilmiş bir paylaşımın fork'lanmış kopyası
        için -- fork, orijinalden farklı bir kullanıcıya aittir (bkz.
        `DraftShareService.respond`), bu yüzden şirket çapında
        (ADMIN/MANAGER/ROOT) bir listelemede ikisinin de ayrı satırlar
        olarak görünmesi gizlenmesi gereken bir yinelenme değil, doğru
        sonuçtur.

        `company_id`'nin `Optional` olmasının tek nedeni `drafts.
        company_id`'nin kendisinin hâlâ öyle olmasıdır (bkz. `DraftModel.
        company_id`'in docstring'i) -- `NULL`'a filtrelenmek yerine
        tamamen atlanır, böylece henüz kiracı (tenant) kapsamına
        geçmemiş bir çağıran, tıpkı öncesinde olduğu gibi tüm şirketlerin
        taslaklarını görmeye devam eder; bu, diğer tüm repository'lerin
        yalnızca satır düzeyi güvenliğe yaslanmak yerine açıkça
        filtreleme kuralına uyar.
        """
        query = self._latest_version_query(company_id, session_id, document_id, user_id)
        query = query.order_by(DraftModel.updated_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_drafts(
        self,
        company_id: Optional[str] = None,
        session_id: Optional[str] = None,
        document_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> int:
        """`list_drafts`'ın kurduğu aynı birleştirilmiş-zincir sorgusu
        üzerinde gerçek bir `SELECT count()` -- bir `list_drafts(...,
        limit=10_000)` + `len()` değil; önceki yaklaşım 10.000 satırı aşan
        her şeyi sessizce eksik sayıyordu (ve bunun maliyetini
        ödüyordu); bu tam olarak `DocumentRepository.count_for_owner`'ın
        önlemek için zaten düzeltildiği anti-pattern."""
        query = self._latest_version_query(company_id, session_id, document_id, user_id)
        result = await self.db.execute(select(func.count()).select_from(query.subquery()))
        return result.scalar_one()

    async def create_version(
        self,
        *,
        user_id: Optional[str],
        company_id: Optional[str] = None,
        session_id: Optional[str],
        document_id: Optional[str],
        content: str,
        parent: Optional[DraftModel] = None,
        correspondence_type: Optional[str] = None,
        destination: Optional[str] = None,
        destination_unit_id: Optional[str] = None,
        destination_justification: Optional[str] = None,
        status: Optional[str] = None,
        confidence_score: Optional[float] = None,
        requires_human_approval: Optional[bool] = None,
        attempts: Optional[int] = None,
        verification: Optional[dict] = None,
        judge: Optional[dict] = None,
        missing_information: Optional[list] = None,
        instructions: Optional[str] = None,
    ) -> DraftModel:
        """Yeni bir versiyon ekle; bu bir revizyon ise `parent`'a zincirlenir."""
        draft = DraftModel(
            id=uuid4().hex,
            company_id=company_id,
            user_id=user_id,
            session_id=session_id,
            document_id=document_id,
            version=(parent.version + 1) if parent is not None else 1,
            parent_draft_id=parent.id if parent is not None else None,
            content=content,
            correspondence_type=correspondence_type,
            destination=destination,
            destination_unit_id=destination_unit_id,
            destination_justification=destination_justification,
            status=status,
            confidence_score=confidence_score,
            requires_human_approval=requires_human_approval,
            attempts=attempts,
            verification=verification,
            judge=judge,
            missing_information=missing_information,
            instructions=instructions,
        )
        self.db.add(draft)
        await self.db.flush()
        return draft

    async def update_destination(
        self,
        draft: DraftModel,
        *,
        destination: str,
        destination_unit_id: Optional[str],
        destination_justification: Optional[str],
    ) -> DraftModel:
        """Bu tek versiyonun yönlendirildiği birimi -- yeni versiyon açmadan, yerinde -- güncelle.

        Kasıtlı olarak `create_version` gibi bir ekleme değil: `destination`
        bu versiyonun metni *hakkında* yönlendirme meta verisidir, metnin
        kendisi değil; bu yüzden onu düzeltmek (insanın en iyi çaba
        önerisinden farklı bir birim seçmesi), gerçek bir içerik
        revizyonunun gerektirdiği gibi tamamen yeni bir taslak versiyonu
        gerektirmez.

        Args:
            draft: Zaten çekilmiş, zaten yetkilendirilmiş, güncellenecek satır.
            destination: Yeni birim adı (gerçek bir `units` satırıyla
                eşleşmeyen serbest metin olabilir -- bkz. `DraftModel`
                üzerindeki `destination_unit_id`'in kendi docstring'i;
                özel bir hedef, routing'in kendi fallback'inin zaten
                tolere ettiği şekilde kabul edilir).
            destination_unit_id: Çözümlenmiş `units.id`, ya da
                `destination` bu şirkette hiçbir birimle eşleşmiyorsa
                `None`.
            destination_justification: Yeni hedefle birlikte kalıcı
                hale getirilecek Türkçe gerekçe, ya da zaten saklanmış
                olanı değiştirmeden bırakmak için `None` (önerilen
                listeden manuel bir seçim, router'ın kendi tahmininin
                yaptığı gibi kendini açıklayan yeni bir cümleye ihtiyaç
                duymaz).
        """
        draft.destination = destination
        draft.destination_unit_id = destination_unit_id
        if destination_justification is not None:
            draft.destination_justification = destination_justification
        await self.db.flush()
        return draft

    async def soft_delete_session(self, session_id: str) -> None:
        """Bir oturumun revizyon zincirindeki her versiyonu silinmiş olarak işaretle.

        `list_drafts`, bir oturumu yalnızca en son versiyonuna indirger
        (yukarıdaki `max(version)` alt sorgusuna bakın) -- yalnızca o tek
        satırı soft-delete yapmak, önceki versiyonu oturumun yeni
        listelemesi olarak "diriltirdi"; bu, UI'dan taslağı silmenin
        anlamı değildir.
        """
        await self.db.execute(
            update(DraftModel)
            .where(DraftModel.session_id == session_id)
            .values(is_deleted=True)
        )
        await self.db.flush()

    async def soft_delete(self, draft_id: str) -> None:
        """Tek bir taslağı silinmiş olarak işaretle -- `session_id=None` olan
        bir taslak için (doğrudan bir `POST /documents/draft` çağrısı),
        burada indirgenecek bir zincir yoktur."""
        await self.db.execute(
            update(DraftModel).where(DraftModel.id == draft_id).values(is_deleted=True)
        )
        await self.db.flush()


class DraftShareRepository:
    """`draft_shares` için repository (bkz. `DraftShareModel`).

    Her metod açık bir `company_id` alır; kiracı (tenancy) işi
    yapıldığından beri diğer tüm repository'lerle aynı gelenek -- RLS
    bunu destekler, yerini almaz.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, share_id: str, company_id: str) -> Optional[DraftShareModel]:
        result = await self.db.execute(
            select(DraftShareModel).where(
                DraftShareModel.id == share_id, DraftShareModel.company_id == company_id
            )
        )
        return result.scalar_one_or_none()

    async def create(self, share: DraftShareModel) -> DraftShareModel:
        self.db.add(share)
        await self.db.flush()
        return share

    def _inbox_query(self, company_id: str, user_id: str, status: Optional[str]):
        query = select(DraftShareModel, DraftModel).join(
            DraftModel, DraftModel.id == DraftShareModel.draft_id
        ).where(
            DraftShareModel.company_id == company_id, DraftShareModel.recipient_id == user_id
        )
        if status is not None:
            query = query.where(DraftShareModel.status == status)
        return query

    async def list_inbox(
        self,
        company_id: str,
        user_id: str,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Tuple[DraftShareModel, DraftModel]]:
        """`user_id`'nin aldığı paylaşımlar, en yeniden en eskiye, taslağın içeriğiyle join edilmiş."""
        query = (
            self._inbox_query(company_id, user_id, status)
            .order_by(DraftShareModel.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return [(share, draft) for share, draft in result.all()]

    async def count_inbox(self, company_id: str, user_id: str, status: Optional[str] = None) -> int:
        query = select(func.count(DraftShareModel.id)).where(
            DraftShareModel.company_id == company_id, DraftShareModel.recipient_id == user_id
        )
        if status is not None:
            query = query.where(DraftShareModel.status == status)
        result = await self.db.execute(query)
        return result.scalar_one()

    async def list_outbox(
        self,
        company_id: str,
        user_id: str,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Tuple[DraftShareModel, DraftModel]]:
        """`user_id`'nin gönderdiği paylaşımlar, en yeniden en eskiye, taslağın içeriğiyle join edilmiş."""
        query = select(DraftShareModel, DraftModel).join(
            DraftModel, DraftModel.id == DraftShareModel.draft_id
        ).where(
            DraftShareModel.company_id == company_id, DraftShareModel.sender_id == user_id
        )
        if status is not None:
            query = query.where(DraftShareModel.status == status)
        query = query.order_by(DraftShareModel.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return [(share, draft) for share, draft in result.all()]

    async def count_outbox(self, company_id: str, user_id: str, status: Optional[str] = None) -> int:
        query = select(func.count(DraftShareModel.id)).where(
            DraftShareModel.company_id == company_id, DraftShareModel.sender_id == user_id
        )
        if status is not None:
            query = query.where(DraftShareModel.status == status)
        result = await self.db.execute(query)
        return result.scalar_one()

    async def mark_read(self, share: DraftShareModel) -> DraftShareModel:
        """Hâlâ `sent` durumundaki bir paylaşımı `read`'e ilerlet. `sent`
        durumunu geçmişse no-op'tur (zaten `accepted`/`rejected`/
        `withdrawn` olan paylaşımlar `read`'e geri dönmez)."""
        if share.status == "sent":
            share.status = "read"
        await self.db.flush()
        return share

    async def respond(
        self, share: DraftShareModel, status: str, response_note: Optional[str]
    ) -> DraftShareModel:
        """Bir paylaşımı `accepted` ya da `rejected` olarak sonuçlandır."""
        share.status = status
        share.response_note = response_note
        share.responded_at = datetime.now(timezone.utc)
        await self.db.flush()
        return share

    async def withdraw(self, share: DraftShareModel) -> DraftShareModel:
        share.status = "withdrawn"
        await self.db.flush()
        return share
