from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class UnitModel(Base, TimestampMixin):
    """SQLAlchemy ORM model for a routable department/unit.

    Replaces the formerly hardcoded ``RoutingPolicy.units`` tuple -- managers
    define and describe units here at runtime, and ``routing_graph`` reads
    them fresh on every routing decision (see ``app.domains.units.provider``).
    """

    __tablename__ = "units"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    #: What the unit handles, in Turkish -- interpolated straight into the
    #: routing prompt so the AI can tell units apart. Required: a unit with
    #: no description gives the router nothing to match content against.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    #: Inactive units are excluded from routing suggestions but kept (not
    #: hard-deleted) so past drafts routed to them stay meaningful; `drafts.
    #: destination` is a free-text column, not a foreign key, so nothing
    #: else references this row by id.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
