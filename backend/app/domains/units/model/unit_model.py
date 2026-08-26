from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class UnitModel(Base, TimestampMixin):
    """Yönlendirilebilir bir departman/birim için SQLAlchemy ORM modeli.

    Eskiden sabit kodlanmış ``RoutingPolicy.units`` demetinin yerini alır --
    yöneticiler birimleri burada, çalışma zamanında tanımlar ve açıklar,
    ``routing_graph`` da her yönlendirme kararında bunları taze okur
    (bkz. ``app.domains.units.provider``).

    Şirket kapsamlı: iki farklı şirket de "İnsan Kaynakları" birimine sahip
    olabilir, bu yüzden benzersizlik salt global ``name`` değil,
    ``(company_id, name)`` üzerinden sağlanır.
    """

    __tablename__ = "units"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_units_company_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    #: Birimin neyle ilgilendiği, Türkçe -- AI'ın birimleri ayırt edebilmesi
    #: için doğrudan yönlendirme promptuna eklenir. Zorunludur: açıklaması
    #: olmayan bir birim, yönlendiriciye içerikle eşleştirecek hiçbir şey
    #: vermez.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    #: Pasif birimler yönlendirme önerilerinden hariç tutulur ama (kalıcı
    #: olarak silinmeden) korunur, böylece bu birimlere yönlendirilmiş
    #: geçmiş taslaklar anlamlı kalır; `drafts.destination` bir yabancı
    #: anahtar değil serbest metin kolonudur, dolayısıyla başka hiçbir şey
    #: bu satıra id ile referans vermez.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
