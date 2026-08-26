from typing import Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class DraftModel(Base, TimestampMixin):
    """Yazılan bir resmi yazışma taslağının bir versiyonu.

    Bir taslağı üreten ya da revize eden her tur için bir satır yazılır --
    asla üzerine yazılmaz, bu yüzden `session_id` + `version` tüm düzenleme
    geçmişini yeniden kurar ve `parent_draft_id` bir revizyonu düzenlediği
    versiyona zincirler. Ayrı bir "geçerli taslak" tablosu yoktur: bir
    `session_id` için en son satır (`version`'a göre) geçerli olandır
    (bkz. `DraftRepository.get_latest_for_session`).

    `session_id` nullable'dır ve FK taşımaz: chat akışı üzerinden üretilen
    bir taslak birleştirilmiş thread_id'yi alır (bkz.
    `ChatService._thread_id`), ama doğrudan bir `POST /documents/draft`
    çağrısının hiç chat oturumu yoktur. `document_id` de aynı şekilde
    `DocumentModel`'in sahiplik konusundaki kendi gevşekliğiyle aynı
    şekilde gevşek, `storage_path` biçiminde bir referanstır.
    """

    __tablename__ = "drafts"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    #: `0016_recorder_tables_rls` migrasyonundan beri NOT NULL -- her
    #: `draft_recorder.record_draft` çağrı noktası tarafından doldurulur;
    #: chat yolunda `PlanningState.company_id` üzerinden de dahil (bkz.
    #: `RunModel.company_id`'in docstring'i).
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )
    session_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    document_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_draft_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("drafts.id"), nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    correspondence_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    destination: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    #: `destination`'ın yazma anında `units`'e karşı çözümlenmiş hali (bkz.
    #: `app.domains.drafts.draft_recorder.record_draft`) -- `destination`
    #: bu şirkette hiçbir birimle eşleşmiyorsa (o zamandan beri yeniden
    #: adlandırılmış/silinmiş, ya da routing boş dönmüş) `None`;
    #: `draft_shares.suggested_unit_id`'in zaten sahip olduğu aynı dürüstlük.
    #: Bir transferin birimler-arası kontrolü ve alıcı önerisi
    #: (`app.domains.transfers`) bunu okur; artık hiçbir şey `destination`'ı
    #: ada göre yeniden çözümlemiyor.
    destination_unit_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("units.id"), nullable=True, index=True
    )
    #: Bu versiyon için routing graph'ın kendi `RouteOutput.justification`'ı
    #: -- routing'i yeniden çalıştırmadan bir transfer onayının "neden bu
    #: birim" gösterebilmesi için kalıcı hale getirilir.
    destination_justification: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    requires_human_approval: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    attempts: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    #: Deterministik doğrulayıcının raporu (bkz. `DraftResponseSchema.verification`).
    verification: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    #: Kalite hakeminin (judge) yapılandırılmış kararı, çalıştıysa (`DraftResponseSchema.judge`).
    judge: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    #: Bu taslağı tamamlamak için kullanıcıya sorulan `List[InfoQuestion]`.
    missing_information: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
