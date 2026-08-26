from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums.sensitivity_level import SensitivityLevel
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class DocumentModel(Base, TimestampMixin):
    """Yüklenen evraklar için sahiplik + listeleme kaydı.

    Evrakın kendi metni ve tam analizi, `app.domains.documents.service.
    DocumentService` tarafından yazılan yerel JSON önbelleğinde kalır (ayrı
    bir konu -- bu blob depolamasını dosya sisteminden taşımak kendi başına,
    daha büyük bir iş, burada kapsam dışı). Bu tablo tam olarak tek bir
    soruyu ucuz ve doğru şekilde yanıtlamak için var: "`storage_path`,
    `owner_id`'ye mi ait?" -- daha önce tamamen eksik olan kontrol (bkz.
    mimari geçişin B8 bulgusu: bir storage_path'i bilen veya tahmin eden
    herhangi bir çağıran, sohbet üzerinden başka bir kullanıcının evrakını
    okuyabiliyordu).

    Kimlik doğrulama artık zorunlu olduğundan (bkz. `settings.REQUIRE_AUTH`)
    `owner_id` ve `company_id` her ikisi de zorunludur -- her evrakın tam
    olarak bir şirkette tam olarak bir yükleyen kullanıcısı vardır. Bu
    migration'dan önceki sahipsiz eski satırlar demo şirket/çalışana
    dolduruldu (bkz. `alembic/versions/0010_backfill_tenancy.py`).
    """

    __tablename__ = "documents"

    #: Depolama arka ucunun anahtarı (bkz. `DocumentService._store`), ayrı
    #: bir surrogate id yerine birincil anahtar olarak yeniden kullanılır --
    #: diğer tüm katmanlar (yerel analiz önbelleği, Qdrant'ın `storage_path`
    #: payload filtresi, API'nin `{storage_path}` yol parametresi) zaten
    #: bir evrakı bu değerle adresliyor.
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    owner_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    document_type: Mapped[str] = mapped_column(String, nullable=False, default="")
    document_type_label: Mapped[str] = mapped_column(String, nullable=False, default="")
    compliance_status: Mapped[str] = mapped_column(String, nullable=False, default="")
    summary: Mapped[str] = mapped_column(String, nullable=False, default="")
    #: Evrakın değerlendirilmiş gizlilik derecesi (``app.ai.guardrails.
    #: sensitivity.assess``), listeleme/erişimin analiz önbelleğini yeniden
    #: okumadan filtreleyebilmesi için ``SensitivityLevel`` string'i olarak
    #: saklanır. Varsayılan olarak ``TASNIF_DISI`` değil ``UNMARKED`` --
    #: `EvrakField.gizlilik_derecesi`'nin zaten belgelediği "eksik bir
    #: derece, belirtilmiş bir dereceyle aynı gerçek değildir" mantığıyla
    #: aynı.
    sensitivity_level: Mapped[str] = mapped_column(
        String, nullable=False, default=SensitivityLevel.UNMARKED.value
    )
    #: Gizlilik derecesinden bağımsız olarak, evrak taraması en az bir
    #: PII kalıp eşleşmesi (TCKN, IBAN, telefon, adres) bulduğunda True.
    pii_flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
