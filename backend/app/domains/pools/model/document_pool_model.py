from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class DocumentPoolModel(Base, TimestampMixin):
    """A named collection of documents belonging to a user, a unit, or a company.

    The shartname's "evrak havuzu" maps to three owner shapes, not one: a
    channel's own personal pool (every upload lands there, lazily created --
    see `DocumentPoolRepository.get_or_create_default`), a unit's shared
    pool a manager pushes into for the whole team, and (reserved, unused
    today) a company-wide pool. `owner_type`/`owner_id` is a loose polymorphic
    reference rather than three nullable FK columns, matching this codebase's
    existing looseness for `permission_grants.subject_type`/`subject_id`.
    """

    __tablename__ = "document_pools"
    __table_args__ = (
        #: At most one *default* pool per owner -- see `permission_grants`'
        #: sibling partial-index pattern in `UnitMembershipModel` for why
        #: this is an `Index`, not a `UniqueConstraint`.
        Index(
            "uq_document_pools_one_default_per_owner",
            "owner_type",
            "owner_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    #: "user" | "unit" | "company".
    owner_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: A `users.id`, `units.id`, or `companies.id` depending on `owner_type`
    #: -- not a foreign key for the same reason `permission_grants.
    #: subject_id` isn't: a single column can't target three different
    #: tables without three nullable FK columns instead of one.
    owner_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    #: The pool `DocumentService` lazily creates and files every upload
    #: into for its owner (see `get_or_create_default`). A user/unit may
    #: have additional, explicitly named pools; only one may be the default.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
