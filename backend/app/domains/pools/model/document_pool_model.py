from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class DocumentPoolModel(Base, TimestampMixin):
    """Bir kullanıcıya, bir birime veya bir şirkete ait adlandırılmış bir
    belge koleksiyonu.

    Şartnamenin "evrak havuzu"su tek değil üç sahip biçimine eşlenir: bir
    kanalın kendi kişisel havuzu (her yükleme oraya iner, tembel olarak
    oluşturulur -- bkz. `DocumentPoolRepository.get_or_create_default`),
    bir manager'ın tüm ekip için push ettiği bir birimin paylaşılan
    havuzu, ve (ayrılmış, bugün kullanılmayan) şirket-geneli bir havuz.
    `owner_type`/`owner_id`, üç nullable FK kolonu yerine gevşek
    polimorfik bir referanstır, bu kod tabanının `permission_grants.
    subject_type`/`subject_id` için mevcut esnekliğiyle eşleşir.
    """

    __tablename__ = "document_pools"
    __table_args__ = (
        #: Sahip başına en fazla bir *varsayılan* havuz -- bunun neden bir
        #: `UniqueConstraint` değil de bir `Index` olduğu için
        #: `UnitMembershipModel`'deki `permission_grants`'ın kardeş
        #: kısmi-index örüntüsüne bakın.
        Index(
            "uq_document_pools_one_default_per_owner",
            "owner_type",
            "owner_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    #: "user" | "unit" | "company".
    #: (owner_type için olası değerler)
    owner_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: A `users.id`, `units.id`, or `companies.id` depending on `owner_type`
    #: -- not a foreign key for the same reason `permission_grants.
    #: subject_id` isn't: a single column can't target three different
    #: tables without three nullable FK columns instead of one.
    owner_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    #: The pool `DocumentService` lazily creates and files every upload
    #: into for its owner (see `get_or_create_default`). A user/unit may
    #: have additional, explicitly named pools; only one may be the default.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
