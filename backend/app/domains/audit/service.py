"""`AuditService` -- the write side (`record`) is best-effort and
deliberately decoupled from the caller's own request-scoped session, the
same convention `app.domains.drafts.draft_recorder`/`app.observability.
run_recorder` already established: a bug or a transient DB error while
writing an audit row must never roll back, block, or fail the actual admin
action it is describing (a company was still created; the fact that
recording that in the audit trail failed is a monitoring gap, not a reason
to also fail the create). Callers invoke `record()` *after* their own
service call has already committed, exactly the ordering those recorders
use.
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
    """The outcome of walking one chain end to end.

    Attributes:
        valid: True iff every row's `hash` matches its recomputed value and
            every row's `prev_hash` matches the previous row's `hash`.
        rows_checked: How many rows were walked (0 for an empty/nonexistent
            chain -- vacuously valid).
        broken_at_seq: The `seq` of the first row that failed either check,
            or `None` if `valid`.
        reason: A short description of what failed, or `None` if `valid`.
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
        """Append one row, on its own session, swallowing any failure.

        `is_root=True` only for the `company_id is None` (system-wide) chain
        -- a company-scoped row still goes through the normal tenant GUC, RLS
        included, same as every other write.
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
        """Walk `company_id`'s chain in `seq` order, recomputing every hash.

        Two independent checks per row: its own `hash` must equal
        `compute_hash(prev_hash_it_recorded, its_own_fields)`, and its
        recorded `prev_hash` must equal the *previous* row's actual `hash`
        (catching a row deleted or reordered out from the middle of the
        chain, which the first check alone would miss).
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
