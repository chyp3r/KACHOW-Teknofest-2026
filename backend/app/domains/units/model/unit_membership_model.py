from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class UnitMembershipModel(Base, TimestampMixin):
    """Kiracılık (tenancy) planının rol matrisinin dayandığı kullanıcı <-> birim bağlantısı.

    Faz 1-3 sisteme kiracı izolasyonu ve yetkilendirme kazandırdı, ama
    "bu birimde kim var" sorusunu yanıtlayacak bir yol yoktu -- ki
    AI önerili taslak alıcıları özelliği (`GET /units/{id}/suggested-recipients`)
    tam olarak buna ihtiyaç duyuyor: `routing_graph`'ın seçtiği birim *adını*
    bir `units` satırıyla eşler, sonra bu tablonun üyeleri öneri olur.

    Bir kullanıcı birden fazla birime ait olabilir (`role_in_unit` bir lider ile
    üyeyi ayırt eder, `units.description` gibi serbest metindir -- yönlendirme
    promptunun kendi gevşekliği), ama şirket genelinde en fazla bir tanesi
    `is_primary` olarak işaretlenebilir; bu kasıtlı olarak burada zorlanmaz:
    birincil olma durumu *bu kullanıcıya* özeldir, tablo genelinde paylaşılmaz,
    bu yüzden basit bir kolon seviyesi bayrak yerine aşağıdaki kısmi (partial)
    benzersiz indeks kullanılır.
    """

    __tablename__ = "unit_memberships"
    __table_args__ = (
        UniqueConstraint("unit_id", "user_id", name="uq_unit_memberships_unit_user"),
        #: Kısmi (partial) benzersiz indeks, bir `UniqueConstraint` değil --
        #: Postgres'te bildirimsel "false iken hariç benzersiz" şekli yok,
        #: bu yüzden bunun yerine `WHERE is_primary` ile kapsamlandırılmış
        #: sade bir indeks kullanılıyor. Mapped kolon nesnesine referans
        #: vermek yerine `text("is_primary")` kullanılıyor: ikincisi
        #: `__table_args__`'ın `is_primary` bağlı bir sınıf özniteliği olarak
        #: var olduktan sonra değerlendirilmesini gerektirirdi, ki tek
        #: seferlik yukarıdan aşağıya sınıf gövdesi çalıştırması sırasında
        #: henüz o değil.
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
    #: Bu üyenin varsayılan/ana birimi; önerilen alıcı sıralaması için
    #: (`is_primary` üyeler sade üyelerden önce önerilir) ve "bu kişinin
    #: rozeti hangi birimi gösteriyor" tarzı UI okumaları için kullanılır.
    #: Her `user_id` için en fazla bir `is_primary=true` satırı olabilir
    #: (yukarıdaki kısmi indekse bakınız).
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Serbest metin, `units.description` ve `drafts.destination` ile aynı
    #: gevşeklikte -- bugün "lead"/"member", kapalı bir kümeye karşı hiç
    #: doğrulanmaz, böylece bir yönetici migration yapmadan bir role etiket
    #: koyabilir.
    role_in_unit: Mapped[Optional[str]] = mapped_column(String, nullable=True)
