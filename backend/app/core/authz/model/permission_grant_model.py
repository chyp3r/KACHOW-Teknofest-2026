from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class PermissionGrantModel(Base, TimestampMixin):
    """ABAC PDP'nin PAP (Policy Administration Point / Politika Yönetim Noktası) deposu.

    Bir satır, yerleşik rol kurallarının (``app.core.authz.rules.BUILTIN_RULES``)
    üzerine açık, şirket kapsamlı bir devirdir -- bir yöneticinin bir
    çalışana kendi yüklemeleri üzerinde ``document:delete`` vermesi, süreli
    bir acil durum (break-glass) yükseltmesi, ya da bir rolün aksi halde
    izin vereceği bir şeyi iptal eden açık bir ``deny``. Buradaki bir
    satırın yerleşik kurallara karşı nasıl tartıldığı için (deny doğrudan
    kazanır; permit'ler arasında en yüksek ``priority`` kazanır)
    ``app.core.authz.engine.authorize``'a bakın.

    ``valid_from``/``valid_until``'ın ayrı bir "delegations" ya da
    "break-glass" tablosu yerine düz, null olabilen zaman damgaları olması
    bilinçlidir: bu sistemin ihtiyaç duyduğu her süreli yükseltme (bir
    yöneticinin geçici devri, zorunlu bir ``reason`` ile kendi kendine
    verilen acil erişim), süresi olan kalıcı bir yetkiyle aynı biçimdedir,
    bu yüzden aynı kalıcılığı, ``granted_by``/``reason`` üzerinden aynı
    denetim izini ve aynı iptal yolunu (``revoked_at``) bedavaya alır.
    """

    __tablename__ = "permission_grants"
    __table_args__ = (
        Index(
            "ix_permission_grants_subject_lookup",
            "company_id",
            "subject_type",
            "subject_id",
            "action",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True, default=lambda: uuid4().hex)
    company_id: Mapped[str] = mapped_column(String, ForeignKey("companies.id"), nullable=False, index=True)
    #: ``"user"`` ya da ``"role"``. ``"unit"``, ``unit_memberships`` var
    #: olduğunda gelecek bir aşama için ayrılmıştır (bkz. kiracılık
    #: planının §1.2'si) ve henüz hiçbir kod yolunun yazdığı ya da
    #: okuduğu bir değer değildir.
    subject_type: Mapped[str] = mapped_column(String, nullable=False)
    #: Bir ``users.id`` (subject_type="user") ya da bir ``UserRole`` değeri
    #: (subject_type="role"). Bir yabancı anahtar değildir: rol tipli bir
    #: yetkinin işaret edeceği tek bir satır yoktur, bu yüzden bu sütun iki
    #: null olabilen FK sütununa bölünmek yerine her iki durum için de düz
    #: bir dize olarak kalır.
    subject_id: Mapped[str] = mapped_column(String, nullable=False)
    #: Bir ``app.core.authz.attributes.Action`` değeri, ya da ``"*"``.
    action: Mapped[str] = mapped_column(String, nullable=False)
    #: Bir ``Resource.type`` değeri ("document", "draft", "unit", ...), ya
    #: da ``"*"``.
    resource_type: Mapped[str] = mapped_column(String, nullable=False)
    #: ``{"any": true}`` | ``{"owner": "self"}`` | ``{"id": "<resource_id>"}``
    #: -- bkz. ``app.core.authz.engine.GrantView.resource_selector``.
    resource_selector: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: Gelecekteki öznitelik-koşullu yetkiler için ayrılmıştır (örn. bir
    #: kaynağın ``sensitivity_rank``'ı) -- henüz ``engine.authorize``
    #: tarafından değerlendirilmiyor. Bir koşul değerlendiren tüketici
    #: eklendiği gün bir yetki satırının biçiminin göç gerektirmemesi için
    #: şimdiden saklanıyor.
    conditions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: ``"permit"`` ya da ``"deny"``. Açık bir deny, priority'den bağımsız
    #: olarak her zaman her permit'in önüne geçer (bkz. ``engine.authorize``).
    effect: Mapped[str] = mapped_column(String, nullable=False, default="permit")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    granted_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    #: İptalde ayarlanır; iptal edilmiş bir satır silinmez, gelecekteki
    #: ``audit_log`` tablosuna katılmak yerine kendi denetim izi olarak
    #: tutulur.
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
