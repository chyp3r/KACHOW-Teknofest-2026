from sqlalchemy import ForeignKey, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin

class InvitedEmailModel(Base, TimestampMixin):
    """Kayıt için beyaz listeye alınmış/davet edilmiş e-postaları saklayan SQLAlchemy ORM modeli.

    ``UserService.register_user``, kayıt olan kişinin ``company_id``'sini
    (ve ``role``'unu) istek gövdesinden değil bu satırdan alır -- self-servis
    kayıt davet ile kısıtlıdır, bu yüzden kayıt olan kişinin kendi şirketini
    seçmesine izin vermek, kiracılar arası kendi kendine atama açığı olurdu.
    """
    __tablename__ = "invited_emails"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="employee")
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
