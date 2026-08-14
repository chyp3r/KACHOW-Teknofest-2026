"""Repository for `audit_log`'s hash chain -- see `AuditLogModel`'s docstring
for the shape and why `company_id` is the one nullable tenant column in this
codebase.
"""

import hashlib
import json
from typing import List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit.model.audit_log_model import AuditLogModel

#: The fixed prev_hash for the first row of any chain (per-company, or the
#: `company_id IS NULL` system-wide chain). Not a real hash of anything --
#: just a stable, recognizable anchor so `_compute_hash` never has to special-
#: case "there is no previous row" inside the hash formula itself.
GENESIS_HASH = "0" * 64


def _canonical_json(payload: dict) -> str:
    """Deterministic JSON encoding -- same key order, no incidental whitespace
    differences -- so the same logical row always hashes to the same value
    regardless of dict insertion order."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str, row: dict) -> str:
    """`sha256(prev_hash || canonical_json(row))`.

    A free function (not a method) so `AuditLogRepository.verify_chain` and
    a future standalone verification script can both recompute a row's
    expected hash from nothing but its own persisted fields, without needing
    a live repository/session.
    """
    payload = _canonical_json(row)
    return hashlib.sha256(f"{prev_hash}|{payload}".encode("utf-8")).hexdigest()


def hashable_fields(entry: AuditLogModel) -> dict:
    """The subset of a row's fields the hash actually covers.

    Deliberately excludes `id` (a random uuid, not a fact about the action)
    and `prev_hash`/`hash` themselves (the hash cannot cover its own value,
    and `prev_hash` is already folded in as the separate chain-linking
    input to `compute_hash`, not part of the JSON payload) -- covering both
    would make every hash trivially self-referential rather than actually
    binding to what happened.
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
    """Append-only store for `audit_log`. There is deliberately no update or
    delete method -- a hash chain that can be edited after the fact is not
    tamper-evident."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _next_seq_and_prev_hash(self, company_id: Optional[str]) -> Tuple[int, str]:
        """The next `seq` and the current chain tip's `hash` for `company_id`'s
        chain (the `company_id IS NULL` system-wide chain included).

        `IS NOT DISTINCT FROM` rather than `==`, so the system-wide chain's
        own `NULL = NULL` comparison behaves as "equal" instead of SQL's
        default "unknown" -- the same fix `DraftRepository.list_drafts`
        needed for the same reason (see that module's docstring).
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
        """Append one row to `company_id`'s chain, computing `seq`/`prev_hash`/
        `hash` in the same call so no caller can construct an inconsistent
        chain link."""
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
        """Every row of one chain, in `seq` order -- what `verify_chain` walks."""
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
        """Newest first -- for `GET /audit`. `company_id=None` (root, no
        company filter) lists every row system-wide, not just the `NULL`
        chain -- unlike `list_chain`/`_next_seq_and_prev_hash`, this is a
        read-side listing filter, not a chain-membership test."""
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
