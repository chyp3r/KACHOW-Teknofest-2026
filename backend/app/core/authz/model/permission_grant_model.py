from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class PermissionGrantModel(Base, TimestampMixin):
    """The ABAC PDP's PAP (Policy Administration Point) store.

    One row is one explicit, company-scoped delegation on top of the
    built-in role rules (``app.core.authz.rules.BUILTIN_RULES``) -- a
    manager granting an employee ``document:delete`` on their own uploads,
    a time-boxed break-glass elevation, or an explicit ``deny`` revoking
    something a role would otherwise permit. See ``app.core.authz.engine.
    authorize`` for how a row here is weighed against the built-in rules
    (deny wins outright; among permits, highest ``priority`` wins).

    ``valid_from``/``valid_until`` being plain nullable timestamps -- not a
    separate "delegations" or "break-glass" table -- is deliberate: every
    time-boxed elevation this system needs (a manager's temporary delegation,
    a self-granted emergency access with a mandatory ``reason``) is the same
    shape as a permanent grant with an expiry, so it gets the same
    persistence, the same audit trail via ``granted_by``/``reason``, and the
    same revocation path (``revoked_at``) for free.
    """

    __tablename__ = "permission_grants"
    __table_args__ = (
        Index(
            "ix_permission_grants_subject_lookup",
            "company_id",
            "subject_type",
            "subject_id",
            "action",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True, default=lambda: uuid4().hex)
    company_id: Mapped[str] = mapped_column(String, ForeignKey("companies.id"), nullable=False, index=True)
    #: ``"user"`` or ``"role"``. ``"unit"`` is reserved for a future phase
    #: once ``unit_memberships`` exists (see the tenancy plan's §1.2) and is
    #: not yet a value any code path writes or reads.
    subject_type: Mapped[str] = mapped_column(String, nullable=False)
    #: A ``users.id`` (subject_type="user") or a ``UserRole`` value
    #: (subject_type="role"). Not a foreign key: a role-typed grant has no
    #: single row to point at, so this column stays a plain string for both
    #: cases rather than splitting into two nullable FK columns.
    subject_id: Mapped[str] = mapped_column(String, nullable=False)
    #: An ``app.core.authz.attributes.Action`` value, or ``"*"``.
    action: Mapped[str] = mapped_column(String, nullable=False)
    #: A ``Resource.type`` value ("document", "draft", "unit", ...), or
    #: ``"*"``.
    resource_type: Mapped[str] = mapped_column(String, nullable=False)
    #: ``{"any": true}`` | ``{"owner": "self"}`` | ``{"id": "<resource_id>"}``
    #: -- see ``app.core.authz.engine.GrantView.resource_selector``.
    resource_selector: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: Reserved for future attribute-conditioned grants (e.g. a resource's
    #: ``sensitivity_rank``) -- not yet evaluated by ``engine.authorize``.
    #: Stored now so a grant row's shape does not need a migration the day
    #: a condition-evaluating consumer is added.
    conditions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: ``"permit"`` or ``"deny"``. An explicit deny always outranks every
    #: permit, regardless of priority (see ``engine.authorize``).
    effect: Mapped[str] = mapped_column(String, nullable=False, default="permit")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    granted_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    #: Set on revocation; a revoked row is kept (not deleted) as its own
    #: audit trail rather than folded into the future ``audit_log`` table.
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
