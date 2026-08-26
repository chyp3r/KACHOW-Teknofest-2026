from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class NotificationModel(Base, TimestampMixin):
    """Bir kullanıcı için uygulama-içi tek bir bildirim.

    Her zaman bir bildirimin kalıcı yarısı: `app.events.subscribers`,
    canlı SSE push için Redis'e yayınlamadan *önce* (`app.domains.
    notifications.router`'ın `/stream`'i) burada bir satır yazar, böylece
    düşen bir Redis mesajı veya bağlantısı kopmuş bir istemci bildirimin
    kendisini asla kaybetmez -- canlı olarak gelmek yerine bir sonraki
    `GET /notifications` sorgulamasında basitçe alınır. Tamamen kişisel:
    documents/drafts/pools'un aksine burada `bypasses_ownership`
    şirket-geneli görünümü yoktur, bir bildirim her zaman yalnızca
    yazıldığı tek `user_id`'ye aittir.
    """

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    #: örn. "draft_shared" | "draft_share_responded" -- kısa bir makine
    #: etiketi, kapalı bir küme olarak zorlanmaz (`document_pool_items.
    #: source`'un esnekliğini yansıtır) böylece gelecekteki bir bildirim
    #: türü hiçbir migration gerektirmez.
    type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Bildirimin ne hakkında olduğu, örn. `resource_type="draft_share"`,
    #: `resource_id=<draft_shares.id>` -- gevşek, bir FK değil, çünkü
    #: `resource_type` `type`'a göre değişir.
    resource_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
