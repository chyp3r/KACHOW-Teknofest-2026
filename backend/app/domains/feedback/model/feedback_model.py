from typing import Optional

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class FeedbackModel(Base, TimestampMixin):
    """Bir kullanıcının, yapay zeka tarafından üretilen bir çıktı üzerindeki
    tek bir 👍/👎'ı.

    Bu, Faz C'nin sonraki aşamalarının (bu migration'ın parçası değil)
    okuduğu ham sinyaldir: çalışma zamanı stil adaptörü (şirket başına,
    C2) ve eğitim için çevrimdışı tercih-çifti veri kümesi (C3), her ikisi
    de burdaki satırlardan ve `drafts` üzerinde zaten kayıtlı olan HITL
    onay/red/revize izinden türetilir -- bugün eğitimle ilgili hiçbir şey
    bu tabloyu doğrudan okumaz, bu kasıtlıdır: "şimdilik yalnızca otomatik
    veri *toplama* çalışır" (bkz. #183/#179'un Faz C çerçevelemesi).

    *Aynı* metin üzerinde tekrar oy vermek, çoğaltmak yerine yeniden oy
    verir: benzersizlik kısıtı herhangi bir mesaj/taslak id'si üzerinde
    değil, `(company_id, user_id, target_kind, content_hash)` üzerindedir;
    çünkü canlı bir sohbet yanıtının gösterildiği anda henüz kalıcı bir
    id'si yoktur (`chat_recorder` bunu turdan sonra asenkron olarak
    kaydeder) -- `content_hash`, her zaman hemen kullanılabilen tek
    kimliktir. `message_id`/`draft_id`, frontend zaten bunlara sahipse
    (örn. geçmişten yüklenen bir mesaja karşı verilen bir oy), sadece
    izlenebilirlik için, en iyi çaba (best-effort) prensibiyle eklenir.

    Burada ham oylanan metin saklanmaz (yalnızca hash'i) -- gerçek içerik
    zaten başka bir yerde kalıcıdır (`chat_messages.content`,
    `drafts.content`) ve bunu burada tekrarlamak, üretilen bir yanıtta
    sonunda yer alan bir belgenin içeriğinin (belgeler hassasiyet
    işaretli olabilir, bkz. `SensitivityLevel`) şifrelenmemiş ikinci bir
    kopyası olurdu; `app.ai.guardrails.pii.PiiFinding`'in asla ham bir
    değer taşımamasıyla aynı gerekçe.
    """

    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "user_id", "target_kind", "content_hash", name="uq_feedback_vote_identity"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("chat_sessions.id"), nullable=True, index=True
    )
    #: Frontend zaten kalıcı bir id'ye sahipse, ilgili `chat_messages`
    #: satırına en iyi çaba (best-effort) ile bağlantı. Bunun neden bir
    #: oyun tekilleştirildiği kimlik olmadığı için sınıf docstring'ine bakın.
    message_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("chat_messages.id"), nullable=True, index=True
    )
    #: `drafts.id`'ye gevşek referans -- FK yok, `DraftModel.document_id`
    #: ile aynı gevşeklik: canlı bir yanıtın da henüz drafts satırı yoktur
    #: (`draft_recorder` da turdan sonra kaydeder), bu yüzden bu alan
    #: yalnızca frontend'de zaten mevcutsa doldurulur (örn. yeniden
    #: yüklenen bir oturumun kalıcı mesaj ayrıntılarından).
    draft_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    #: "draft" | "revision" | "assist_reply" | "routing" -- kapalı bir küme
    #: olarak zorlanmaz (`NotificationModel.type`'ın gevşekliğini
    #: yansıtır), böylece oylanabilir yeni bir yüzey migration
    #: gerektirmez.
    target_kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: "like" | "dislike".
    signal: Mapped[str] = mapped_column(String, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Opsiyonel yapılandırılmış etiketler, örn.
    #: `{"uslup": true, "dogruluk": false}` -- oyun aslında kalitenin
    #: hangi boyutuyla ilgili olduğu. Sabit bir sütun kümesi değil,
    #: serbest formatlı JSON; çünkü boyut listesi, backend'in değiştirmek
    #: için migration'a ihtiyaç duymaması gereken bir ürün/UX kararıdır.
    dimensions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    #: Oylanan metnin sha256'sı -- oyun gerçek kimliği (bkz. sınıf
    #: docstring'i), asla metnin kendisi değil.
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    #: Geldiği her tabloyu yeniden join etmeden sonraki eğitim verisi
    #: türetimi için kullanışlı, belirli bir andaki bağlam anlık görüntüsü,
    #: örn.
    #: `{"correspondence_type": ..., "confidence_score": ..., "applied_rules": [...]}`.
    context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
