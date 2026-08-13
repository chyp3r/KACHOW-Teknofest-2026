from typing import Optional

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class CompanyModel(Base, TimestampMixin):
    """SQLAlchemy ORM model for a tenant company.

    The root of the multi-tenancy hierarchy: every company-scoped row in the
    system (``users``, ``units``, ``documents``, ``drafts``, ...) carries a
    ``company_id`` foreign key back to this table. See
    ``app.core.permissions.role_checker.bypasses_ownership`` for how that
    boundary composes with role-based ownership bypass.
    """

    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    #: Human-readable, URL/label-safe identifier -- used as the storage path
    #: prefix for uploads (``uploads/{slug}/...``) and as the Grafana/
    #: Langfuse label value, since the uuid ``id`` is not something a human
    #: reading a dashboard or a filesystem should have to resolve.
    slug: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    tax_number: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Per-company feature flags and preferences (e.g. future opt-in MFA,
    #: routing calibration notes). Kept as a JSON bag rather than columns so
    #: adding a company-level toggle never needs a migration.
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: The root user who created this company. Nullable so the demo-company
    #: seed row (created before any root user exists) doesn't need a
    #: chicken-and-egg workaround.
    created_by: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
