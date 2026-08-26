from typing import Optional

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class CompanyModel(Base, TimestampMixin):
    """Bir kiracı şirket için SQLAlchemy ORM modeli.

    Çoklu kiracılık (multi-tenancy) hiyerarşisinin kökü: sistemdeki
    şirkete özel her satır (``users``, ``units``, ``documents``,
    ``drafts``, ...) bu tabloya geri işaret eden bir ``company_id``
    foreign key taşır. Bu sınırın rol tabanlı sahiplik bypass'ıyla nasıl
    bir araya geldiği için ``app.core.permissions.role_checker.
    bypasses_ownership``'e bakın.
    """

    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    #: İnsan tarafından okunabilir, URL/etiket açısından güvenli tanımlayıcı --
    #: yüklemeler için depolama yolu öneki (``uploads/{slug}/...``) ve
    #: Grafana/Langfuse etiket değeri olarak kullanılır; çünkü uuid olan
    #: ``id``, bir dashboard veya dosya sistemini okuyan bir insanın
    #: çözmek zorunda kalması gereken bir şey değildir.
    slug: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    tax_number: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Şirket başına özellik bayrakları ve tercihler (ör. ileride opt-in
    #: MFA, yönlendirme kalibrasyon notları). Şirket düzeyinde bir açma/
    #: kapama eklemek asla migration gerektirmesin diye sütunlar yerine
    #: bir JSON torbası olarak tutulur.
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: Bu şirketi oluşturan root kullanıcı. Nullable, çünkü demo şirket seed
    #: satırının (henüz hiçbir root kullanıcı yokken oluşturulur) tavuk-
    #: yumurta sorununa bir çözüme ihtiyacı olmasın diye.
    created_by: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
