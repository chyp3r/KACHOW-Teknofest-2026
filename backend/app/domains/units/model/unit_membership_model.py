from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class UnitMembershipModel(Base, TimestampMixin):
    """The user <-> unit link the tenancy plan's role matrix relies on.

    Faz 1-3 gave the system tenant isolation and authorization, but no way
    to answer "who is in this unit" -- which the AI-suggested draft
    recipients feature (`GET /units/{id}/suggested-recipients`) needs
    directly: it maps `routing_graph`'s chosen unit *name* to a `units` row,
    then this table's members are the suggestion.

    A user may belong to several units (`role_in_unit` distinguishes a lead
    from a member, free text like `units.description` is -- the routing
    prompt's own looseness), but at most one may be marked `is_primary`
    company-wide is not enforced here on purpose: primary-ness is scoped to
    *this user*, not shared across the table, hence the partial unique index
    below rather than a simple column-level flag.
    """

    __tablename__ = "unit_memberships"
    __table_args__ = (
        UniqueConstraint("unit_id", "user_id", name="uq_unit_memberships_unit_user"),
        #: Partial unique index, not a `UniqueConstraint` -- Postgres has no
        #: declarative "unique except when false" shape, so this is a plain
        #: index scoped by `WHERE is_primary` instead. `text("is_primary")`
        #: rather than referencing the mapped column object: the latter
        #: would need `__table_args__` to be evaluated after `is_primary`
        #: exists as a bound class attribute, which it isn't yet during a
        #: single top-to-bottom class body execution.
        Index(
            "uq_unit_memberships_one_primary_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    unit_id: Mapped[str] = mapped_column(String, ForeignKey("units.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    #: This member's default/home unit, for suggested-recipient ranking
    #: (`is_primary` members are suggested ahead of plain members) and for
    #: "which unit does this person's badge show" style UI reads. At most
    #: one `is_primary=true` row per `user_id` (see the partial index above).
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Free text, same looseness as `units.description` and `drafts.
    #: destination` -- "lead"/"member" today, never validated against a
    #: closed set so a manager can label a role without a migration.
    role_in_unit: Mapped[Optional[str]] = mapped_column(String, nullable=True)
