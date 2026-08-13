from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.core.enums.sensitivity_level import SensitivityLevel
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin

class UserModel(Base, TimestampMixin):
    """SQLAlchemy ORM model for user accounts supporting role-based authorization."""
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "company_id IS NOT NULL OR role = 'root'",
            name="ck_users_company_id_required_unless_root",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    #: NULL only for role='root' (see the check constraint above) -- root is
    #: the one role not bound to any single tenant, and reaches a company's
    #: data only through the explicit scope-switch path, never through this
    #: column. Every other role must belong to exactly one company.
    company_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("companies.id"), nullable=True, index=True
    )
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="employee")
    #: Individual confidentiality ceiling for an EMPLOYEE-role user (see
    #: app.core.permissions.role_checker.clearance_for). Meaningless for
    #: ADMIN/MANAGER, who clear every level by role alone -- kept on every
    #: user row anyway rather than nullable-for-non-employees, so a role
    #: change from EMPLOYEE to something else never leaves a stale
    #: nullable/non-nullable mismatch to migrate around.
    clearance_level: Mapped[str] = mapped_column(
        String, nullable=False, default=SensitivityLevel.HIZMETE_OZEL.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
