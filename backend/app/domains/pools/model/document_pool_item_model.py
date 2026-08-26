from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class DocumentPoolItemModel(Base, TimestampMixin):
    """Bir havuza dosyalanmış tek bir belge (bkz. `DocumentPoolModel`).

    Bir belge birden fazla havuzda bulunabilir (bir manager'ın bir
    çalışanın kişisel havuzuna push etmesi, belgeyi zaten olduğu yerden
    kaldırmaz), bu yüzden bu bir join satırıdır, `documents`'ın kendisi
    üzerinde bir `pool_id` kolonu değil -- `UNIQUE(pool_id, document_id)`
    yalnızca aynı belgenin *aynı* havuzda iki kez görünmesini engeller.
    """

    __tablename__ = "document_pool_items"
    __table_args__ = (
        UniqueConstraint("pool_id", "document_id", name="uq_document_pool_items_pool_document"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    pool_id: Mapped[str] = mapped_column(
        String, ForeignKey("document_pools.id"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(
        String, ForeignKey("documents.id"), nullable=False, index=True
    )
    added_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    #: "upload" (sahibinin kendi belgesi, otomatik dosyalanmış) |
    #: "manager_push" (`POST /pools/push`) | "transfer"
    #: (`app.domains.transfers.ArtifactTransferService` -- daha önce
    #: ayrılmış olan `"share"` değerinin yerine geçti; bunu gerçekten
    #: uygulayan domain'e uyacak şekilde yeniden adlandırıldı, aşağıdaki
    #: `metadata_snapshot`'a bakın) | "adopted" (`POST
    #: /pools/items/{id}/adopt`, Faz 5, #205 -- havuzun kendi sahibinin
    #: tamamen sahip olunan bir kopyaya dönüştürdüğü bir `"transfer"`
    #: öğesi; `document_id` artık göndereninki yerine kendi `documents`
    #: satırına işaret eder).
    source: Mapped[str] = mapped_column(String, nullable=False, default="upload")
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: Havuzun sahibi push edilmiş bir öğeyi onayladığında/okuduğunda
    #: ayarlanır (`POST /pools/items/{id}/acknowledge`). Düz bir "upload"
    #: öğesi için sonsuza dek `NULL` -- onaylama yalnızca sana *push
    #: edilmiş* bir şey için bir anlam ifade eder.
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    #: `source="transfer"` için gönderen -- `added_by`'dan farklıdır,
    #: bir transfer için o satırı fiilen ekleyen sürecin kim olduğudur
    #: (bugün chat/rest kanallarındaki işlemi yapan kullanıcı; gelecekte
    #: system tarafından başlatılan bir yol farklı olabilir). "upload"/
    #: "manager_push" için `NULL`. `adopt`'tan sonra bile (yukarıdaki
    #: `source`'a bakın) köken olarak hayatta kalır -- alıcı snapshot'ı
    #: kendi sahip olduğu bir kopyaya dönüştürdükten sonra bile onu
    #: kimin gönderdiği gerçek kalır.
    transferred_by: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    #: `documents`'ın değişebilir metadata'sı (document_type,
    #: document_type_label, compliance_status, summary, sensitivity_level,
    #: pii_flagged), transfer anında dondurulmuş. Blob'un kendisi bu
    #: sistemdeki hiçbir şey tarafından asla mutasyona uğratılmaz, bu
    #: yüzden paylaşmak güvenlidir; gönderen kaynak belgeyi sonradan
    #: düzenlerse alıcının altından kayabilecek şey bu satırın kendi
    #: metadata'sıdır -- tam bir kopyanın neden bu snapshot lehine
    #: reddedildiği için planın §D5'ine bakın. "transfer" dışındaki her
    #: kaynak için `NULL` -- `adopt` tarafından da `NULL`'a geri
    #: temizlenir, çünkü benimsenmiş bir öğenin `documents` satırı artık
    #: canlı ve sahiplidir, başkasının dondurulmuş bir snapshot'ı değil.
    metadata_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
