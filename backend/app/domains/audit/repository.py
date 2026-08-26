"""`audit_log`'un hash zinciri için repository -- şeklini ve `company_id`'nin
bu kod tabanındaki nullable olan tek kiracı sütunu olmasının nedenini
`AuditLogModel`'in docstring'inde bulabilirsiniz.
"""

import hashlib
import json
from typing import List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit.model.audit_log_model import AuditLogModel

#: Herhangi bir zincirin ilk satırı için sabit prev_hash (şirket başına,
#: veya `company_id IS NULL` sistem geneli zincir). Gerçekten bir şeyin
#: hash'i değil -- sadece kararlı, tanınabilir bir çapa, böylece
#: `_compute_hash` hash formülünün içinde "önceki satır yok" durumunu
#: özel olarak ele almak zorunda kalmaz.
GENESIS_HASH = "0" * 64


def _canonical_json(payload: dict) -> str:
    """Deterministik JSON kodlaması -- aynı anahtar sırası, tesadüfi boşluk
    farkı yok -- böylece aynı mantıksal satır, dict ekleme sırasından
    bağımsız olarak her zaman aynı değere hash'lenir."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str, row: dict) -> str:
    """`sha256(prev_hash || canonical_json(row))`.

    Bir metot değil, bağımsız (free) bir fonksiyon; böylece
    `AuditLogRepository.verify_chain` ve gelecekteki bağımsız bir doğrulama
    betiği, canlı bir repository/session'a ihtiyaç duymadan bir satırın
    beklenen hash'ini sadece kendi kalıcı hale getirilmiş alanlarından
    yeniden hesaplayabilir.
    """
    payload = _canonical_json(row)
    return hashlib.sha256(f"{prev_hash}|{payload}".encode("utf-8")).hexdigest()


def hashable_fields(entry: AuditLogModel) -> dict:
    """Bir satırın alanlarından hash'in gerçekte kapsadığı alt küme.

    Bilinçli olarak `id`'yi (rastgele bir uuid, eylem hakkında bir gerçek
    değil) ve `prev_hash`/`hash`'in kendisini (hash kendi değerini
    kapsayamaz, ve `prev_hash` zaten `compute_hash`'e ayrı bir zincir-bağlama
    girdisi olarak katılıyor, JSON payload'ının bir parçası değil) dışarıda
    bırakır -- ikisini de kapsamak, her hash'i gerçekte olanı bağlamak
    yerine önemsiz biçimde kendine referans veren bir şey yapardı.
    """
    return {
        "company_id": entry.company_id,
        "seq": entry.seq,
        "actor_user_id": entry.actor_user_id,
        "actor_role": entry.actor_role,
        "acting_as_company_id": entry.acting_as_company_id,
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "decision": entry.decision,
        "reason": entry.reason,
        "before": entry.before,
        "after": entry.after,
        "ip": entry.ip,
        "correlation_id": entry.correlation_id,
    }


class AuditLogRepository:
    """`audit_log` için sadece-ekleme (append-only) veri deposu. Bilinçli
    olarak update veya delete metodu yok -- sonradan düzenlenebilen bir hash
    zinciri kurcalamaya karşı kanıt sağlamaz (tamper-evident değildir)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _next_seq_and_prev_hash(self, company_id: Optional[str]) -> Tuple[int, str]:
        """`company_id`'nin zinciri için bir sonraki `seq` ve mevcut zincir
        ucunun `hash`'i (`company_id IS NULL` sistem geneli zincir dahil).

        `==` yerine `IS NOT DISTINCT FROM`, böylece sistem geneli zincirin
        kendi `NULL = NULL` karşılaştırması SQL'in varsayılan "bilinmiyor"u
        yerine "eşit" olarak davranır -- `DraftRepository.list_drafts`'ın
        aynı nedenle ihtiyaç duyduğu düzeltmenin aynısı (bkz. o modülün
        docstring'i).
        """
        result = await self.db.execute(
            select(AuditLogModel)
            .where(AuditLogModel.company_id.is_not_distinct_from(company_id))
            .order_by(AuditLogModel.seq.desc())
            .limit(1)
        )
        tip = result.scalar_one_or_none()
        if tip is None:
            return 1, GENESIS_HASH
        return tip.seq + 1, tip.hash

    async def append(
        self,
        *,
        company_id: Optional[str],
        actor_user_id: Optional[str],
        actor_role: Optional[str],
        action: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        decision: str = "permit",
        reason: Optional[str] = None,
        before: Optional[dict] = None,
        after: Optional[dict] = None,
        ip: Optional[str] = None,
        correlation_id: Optional[str] = None,
        acting_as_company_id: Optional[str] = None,
    ) -> AuditLogModel:
        """`company_id`'nin zincirine bir satır ekle, `seq`/`prev_hash`/`hash`'i
        aynı çağrıda hesaplayarak hiçbir çağıranın tutarsız bir zincir
        bağlantısı oluşturamamasını sağla."""
        seq, prev_hash = await self._next_seq_and_prev_hash(company_id)
        entry = AuditLogModel(
            id=uuid4().hex,
            company_id=company_id,
            seq=seq,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            acting_as_company_id=acting_as_company_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            decision=decision,
            reason=reason,
            before=before,
            after=after,
            ip=ip,
            correlation_id=correlation_id,
            prev_hash=prev_hash,
        )
        entry.hash = compute_hash(prev_hash, hashable_fields(entry))
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def list_chain(self, company_id: Optional[str]) -> List[AuditLogModel]:
        """Bir zincirin `seq` sırasındaki tüm satırları -- `verify_chain`'in gezdiği veri."""
        result = await self.db.execute(
            select(AuditLogModel)
            .where(AuditLogModel.company_id.is_not_distinct_from(company_id))
            .order_by(AuditLogModel.seq.asc())
        )
        return list(result.scalars().all())

    async def list_filtered(
        self,
        company_id: Optional[str],
        actor_user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[AuditLogModel]:
        """En yeni önce -- `GET /audit` için. `company_id=None` (root, şirket
        filtresi yok) sadece `NULL` zincirini değil, sistem genelindeki her
        satırı listeler -- `list_chain`/`_next_seq_and_prev_hash`'in aksine,
        bu bir okuma-tarafı listeleme filtresidir, zincir-üyeliği testi
        değil."""
        query = select(AuditLogModel)
        if company_id is not None:
            query = query.where(AuditLogModel.company_id == company_id)
        if actor_user_id is not None:
            query = query.where(AuditLogModel.actor_user_id == actor_user_id)
        if action is not None:
            query = query.where(AuditLogModel.action == action)
        if resource_type is not None:
            query = query.where(AuditLogModel.resource_type == resource_type)
        query = query.order_by(AuditLogModel.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_filtered(
        self,
        company_id: Optional[str],
        actor_user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
    ) -> int:
        query = select(func.count(AuditLogModel.id))
        if company_id is not None:
            query = query.where(AuditLogModel.company_id == company_id)
        if actor_user_id is not None:
            query = query.where(AuditLogModel.actor_user_id == actor_user_id)
        if action is not None:
            query = query.where(AuditLogModel.action == action)
        if resource_type is not None:
            query = query.where(AuditLogModel.resource_type == resource_type)
        result = await self.db.execute(query)
        return result.scalar_one()
