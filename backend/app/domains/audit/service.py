"""`AuditService` -- yazma tarafı (`record`) en iyi çaba (best-effort)
prensibiyle çalışır ve bilinçli olarak çağıranın kendi istek kapsamlı
session'ından ayrıştırılmıştır; `app.domains.drafts.draft_recorder`/
`app.observability.run_recorder`'ın zaten yerleştirdiği aynı kural: bir
audit satırı yazılırken oluşan bir hata veya geçici bir DB hatası, tarif
ettiği asıl yönetici eylemini asla geri almamalı, engellememeli veya
başarısız kılmamalıdır (şirket yine de oluşturuldu; bunu audit izinde
kaydetmenin başarısız olması bir izleme (monitoring) eksikliğidir,
oluşturmayı da başarısız saymak için bir neden değildir). Çağıranlar
`record()`'u kendi servis çağrıları zaten commit edildikten *sonra*
çağırır, tam olarak o recorder'ların kullandığı sırayla.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

from app.domains.audit.model.audit_log_model import AuditLogModel
from app.domains.audit.repository import GENESIS_HASH, AuditLogRepository, compute_hash, hashable_fields
from app.infrastructure.database.session import tenant_session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChainVerificationResult:
    """Bir zinciri baştan sona gezmenin sonucu.

    Attributes:
        valid: Yalnızca ve yalnızca her satırın `hash`'i yeniden hesaplanan
            değeriyle ve her satırın `prev_hash`'i önceki satırın `hash`'iyle
            eşleşiyorsa True.
        rows_checked: Kaç satırın gezildiği (boş/var olmayan bir zincir için
            0 -- anlamsız biçimde geçerli).
        broken_at_seq: İki kontrolden birini geçemeyen ilk satırın `seq`'i,
            ya da `valid` ise `None`.
        reason: Neyin başarısız olduğuna dair kısa bir açıklama, ya da
            `valid` ise `None`.
    """

    valid: bool
    rows_checked: int
    broken_at_seq: Optional[int] = None
    reason: Optional[str] = None


class AuditService:
    def __init__(self, repository: AuditLogRepository):
        self.repository = repository

    async def record(
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
    ) -> None:
        """Kendi session'ında bir satır ekle, oluşan her hatayı yut.

        `is_root=True` yalnızca `company_id is None` (sistem geneli) zinciri
        için -- şirket kapsamlı bir satır yine de normal kiracı GUC'undan
        geçer, RLS dahil, diğer her yazma işlemiyle aynı şekilde.
        """
        try:
            async with tenant_session(company_id, is_root=company_id is None) as session:
                await AuditLogRepository(session).append(
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    actor_role=actor_role,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    decision=decision,
                    reason=reason,
                    before=before,
                    after=after,
                    ip=ip,
                    correlation_id=correlation_id,
                    acting_as_company_id=acting_as_company_id,
                )
        except Exception:
            logger.warning("audit_log write failed for action=%s", action, exc_info=True)

    async def list_entries(
        self,
        company_id: Optional[str],
        actor_user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[AuditLogModel]:
        return await self.repository.list_filtered(
            company_id, actor_user_id, action, resource_type, skip=skip, limit=limit
        )

    async def count_entries(
        self,
        company_id: Optional[str],
        actor_user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
    ) -> int:
        return await self.repository.count_filtered(company_id, actor_user_id, action, resource_type)

    async def verify_chain(self, company_id: Optional[str]) -> ChainVerificationResult:
        """`company_id`'nin zincirini `seq` sırasında gez, her hash'i yeniden hesapla.

        Satır başına iki bağımsız kontrol: kendi `hash`'i
        `compute_hash(prev_hash_it_recorded, its_own_fields)`'e eşit olmalı,
        ve kaydedilmiş `prev_hash`'i *önceki* satırın gerçek `hash`'ine eşit
        olmalı (zincirin ortasından silinmiş veya sırası değiştirilmiş bir
        satırı yakalar, ki bunu tek başına ilk kontrol kaçırırdı).
        """
        rows = await self.repository.list_chain(company_id)
        expected_prev = GENESIS_HASH
        for index, row in enumerate(rows):
            if row.prev_hash != expected_prev:
                return ChainVerificationResult(
                    valid=False,
                    rows_checked=index + 1,
                    broken_at_seq=row.seq,
                    reason="prev_hash zincirdeki bir önceki satırın hash'iyle eşleşmiyor",
                )
            recomputed = compute_hash(row.prev_hash, hashable_fields(row))
            if recomputed != row.hash:
                return ChainVerificationResult(
                    valid=False,
                    rows_checked=index + 1,
                    broken_at_seq=row.seq,
                    reason="satırın hash'i kendi alanlarından yeniden hesaplananla eşleşmiyor",
                )
            expected_prev = row.hash
        return ChainVerificationResult(valid=True, rows_checked=len(rows))
