from sqlalchemy import ForeignKey, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin

class InvitedEmailModel(Base, TimestampMixin):
    """SQLAlchemy ORM model storing whitelisted/invited emails for registration.

    ``UserService.register_user`` takes the registrant's ``company_id`` (and
    ``role``) from this row, not from the request body -- self-service
    registration is invite-gated, so letting a registrant pick their own
    company would be a cross-tenant self-assignment hole.
    """
    __tablename__ = "invited_emails"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="employee")
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
