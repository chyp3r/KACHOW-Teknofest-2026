from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.core.enums.sensitivity_level import SensitivityLevel
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin

class UserModel(Base, TimestampMixin):
    """SQLAlchemy ORM model for user accounts supporting role-based authorization."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
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
