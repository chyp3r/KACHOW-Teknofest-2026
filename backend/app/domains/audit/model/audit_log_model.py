from typing import Optional

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class AuditLogModel(Base, TimestampMixin):
    """Bir şirketin (veya root'un sistem geneli) audit hash zincirinde
    kurcalamaya karşı kanıt sağlayan (tamper-evident) tek bir satır.

    `hash = sha256(prev_hash || canonical_json(row))` (bkz.
    `AuditLogRepository._compute_hash`) -- `prev_hash`, *aynı* zincirdeki
    önceki satıra geri bağlanır, bu yüzden herhangi bir satırı değiştirmek
    veya silmek ondan sonraki her hash'i bozar. `seq` *bir zincir içinde*
    monoton artar, global olarak değil: `verify_chain` bir `company_id`
    için satırları `seq` sırasında gezer ve zinciri sıfırdan yeniden
    hesaplar.

    `company_id` nullable'dır -- bu kod tabanının kiracı tablolarındaki tek
    istisna -- çünkü bir `UserRole.ROOT` öznesi, hedefi tek bir şirket
    olmayan gerçekten sistem geneli eylemler gerçekleştirebilir (aynı izin
    için bkz. `app.core.authz.attributes.Resource.company_id`'nin kendi
    docstring'i). Bu, RLS'yi zayıflatmaz: mevcut `tenant_isolation`
    politikası şekli (`company_id = current_setting(...) OR is_root`) zaten
    `NULL` bir `company_id`'yi "yalnızca `app.is_root` altında görünür"
    olarak çözer, ki bu tam olarak sistem geneli bir satır için amaçlanan
    görünürlüktür.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        #: Postgres, birden fazla `company_id IS NULL` satırını bir UNIQUE
        #: kısıtı altında çakışıyor saymaz (`NULL <> NULL`), bu yüzden bu
        #: kısıt tek başına sistem geneli (`company_id IS NULL`) zincirin
        #: sıra tekilliğini (sequence uniqueness) denetleyemez --
        #: `AuditLogRepository.append`, `seq`'i tam olarak o zincir için de
        #: doğru kalması için `company_id IS NOT DISTINCT FROM :company_id`
        #: üzerinden hesaplar (`DraftRepository.list_drafts`'ta düzeltilen
        #: aynı sınıftan NULL-gruplama hatası).
        UniqueConstraint("company_id", "seq", name="uq_audit_log_company_seq"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("companies.id"), nullable=True, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )
    actor_role: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: Yalnızca bir ROOT öznesi (henüz uygulanmamış -- bkz. kiracılık
    #: planının kapsam-değiştirme başlığına dair kendi §1.1 notu)
    #: `X-Company-Scope` yolu üzerinden hareket ettiğinde ayarlanır; bu
    #: aşamanın gerçekte yazdığı her satır dahil, geri kalan her şey için
    #: `NULL`.
    acting_as_company_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False, index=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: "permit" | "deny" -- `app.core.authz.engine.Decision.permit`'i
    #: yansıtır, ama bu tablo arkasında hiç ABAC kararı olmayan eylemleri de
    #: kaydeder (ROOT tarafından bir şirket oluşturmanın bildirecek bir
    #: `authorize()` çağrısı yoktur), burada bu basitçe "permit"tir (eylem
    #: gerçekleşti).
    decision: Mapped[str] = mapped_column(String, nullable=False, default="permit")
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    before: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    prev_hash: Mapped[str] = mapped_column(String, nullable=False)
    hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
