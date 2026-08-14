from typing import Optional

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class AuditLogModel(Base, TimestampMixin):
    """One tamper-evident row in a company's (or root's system-wide) audit
    hash chain.

    `hash = sha256(prev_hash || canonical_json(row))` (see
    `AuditLogRepository._compute_hash`) -- `prev_hash` links back to the
    previous row in the *same* chain, so altering or deleting any row
    breaks every hash after it. `seq` is monotonic *within one chain*, not
    globally: `verify_chain` walks rows in `seq` order for one `company_id`
    and recomputes the chain from scratch.

    `company_id` is nullable -- the one exception among this codebase's
    tenant tables -- because a `UserRole.ROOT` subject can perform genuinely
    system-wide actions with no single company as their target (see
    `app.core.authz.attributes.Resource.company_id`'s own docstring for the
    same allowance). This does not weaken RLS: the existing
    `tenant_isolation` policy shape (`company_id = current_setting(...) OR
    is_root`) already resolves a `NULL` `company_id` to "only visible under
    `app.is_root`", which is exactly the intended visibility for a
    system-wide row.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        #: Postgres does NOT treat multiple `company_id IS NULL` rows as
        #: colliding under a UNIQUE constraint (`NULL <> NULL`), so this
        #: constraint alone cannot police the system-wide (`company_id IS
        #: NULL`) chain's sequence uniqueness -- `AuditLogRepository.append`
        #: computes `seq` via `company_id IS NOT DISTINCT FROM :company_id`
        #: specifically to stay correct for that chain too (the same class
        #: of NULL-grouping bug fixed in `DraftRepository.list_drafts`).
        UniqueConstraint("company_id", "seq", name="uq_audit_log_company_seq"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("companies.id"), nullable=True, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )
    actor_role: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: Set only when a ROOT subject acted through the (not-yet-implemented --
    #: see the tenancy plan's own §1.1 note on the scope-switch header)
    #: `X-Company-Scope` path; `NULL` for everything else, including every
    #: row this phase actually writes.
    acting_as_company_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False, index=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: "permit" | "deny" -- mirrors `app.core.authz.engine.Decision.permit`,
    #: but this table also records actions with no ABAC decision behind
    #: them at all (a company create by ROOT has no `authorize()` call to
    #: report), where this is simply "permit" (the action happened).
    decision: Mapped[str] = mapped_column(String, nullable=False, default="permit")
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    before: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    prev_hash: Mapped[str] = mapped_column(String, nullable=False)
    hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
