from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.core.enums.sensitivity_level import SensitivityLevel
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin

class UserModel(Base, TimestampMixin):
    """Rol tabanlı yetkilendirmeyi destekleyen kullanıcı hesapları için SQLAlchemy ORM modeli."""
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "company_id IS NOT NULL OR role = 'root'",
            name="ck_users_company_id_required_unless_root",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    #: Sadece role='root' için NULL olur (yukarıdaki check constraint'e
    #: bakınız) -- root, tek bir kiracıya bağlı olmayan tek roldür ve bir
    #: şirketin verisine bu kolon üzerinden değil, sadece açık kapsam
    #: değiştirme (scope-switch) yolu üzerinden ulaşır. Diğer her rol tam
    #: olarak bir şirkete ait olmalıdır.
    company_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("companies.id"), nullable=True, index=True
    )
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="employee")
    #: EMPLOYEE rolündeki bir kullanıcı için bireysel gizlilik tavanı
    #: (bkz. app.core.permissions.role_checker.clearance_for). Sadece rolüyle
    #: her seviyeyi geçen ADMIN/MANAGER için anlamsızdır -- yine de
    #: EMPLOYEE-olmayanlar için nullable yapmak yerine her kullanıcı
    #: satırında tutulur, böylece EMPLOYEE'den başka bir role geçiş, etrafında
    #: migration yapılması gereken bayat bir nullable/non-nullable
    #: uyuşmazlığı bırakmaz.
    clearance_level: Mapped[str] = mapped_column(
        String, nullable=False, default=SensitivityLevel.HIZMETE_OZEL.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
