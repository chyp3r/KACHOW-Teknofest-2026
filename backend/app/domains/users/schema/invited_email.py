from pydantic import BaseModel, EmailStr, Field
from app.core.enums.user_role import UserRole

class InvitedEmailCreate(BaseModel):
    """Pydantic schema to whitelist/invite an email."""
    email: EmailStr = Field(description="Invited email address")
    role: UserRole = Field(default=UserRole.EMPLOYEE, description="Pre-assigned role for the invitee")

class InvitedEmailResponse(BaseModel):
    """Pydantic schema returning whitelisted/invited email details."""
    id: str = Field(description="Unique invitation ID")
    email: EmailStr = Field(description="Invited email address")
    role: UserRole = Field(description="Pre-assigned role")
    is_used: bool = Field(description="Invitation utilization status")

    model_config = {
        "from_attributes": True
    }
