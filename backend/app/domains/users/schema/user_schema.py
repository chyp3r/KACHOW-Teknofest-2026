from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from app.core.enums.sensitivity_level import SensitivityLevel
from app.core.enums.user_role import UserRole

class UserCreate(BaseModel):
    """Pydantic schema for creating a new user account.

    Deliberately has no ``clearance_level`` field: registration is
    self-service (gated only by the invite whitelist, no auth required), so
    letting a registrant set their own confidentiality ceiling would be a
    self-escalation hole. Every new account starts at
    ``UserModel.clearance_level``'s column default and can only be raised
    afterwards by an admin via ``PUT /users/{id}``.
    """
    username: str = Field(description="Unique username")
    email: EmailStr = Field(description="Unique email address")
    password: str = Field(description="Plain text password")
    role: UserRole = Field(default=UserRole.EMPLOYEE, description="Assigned role for authorization")

class UserUpdate(BaseModel):
    """Pydantic schema for updating a user account."""
    email: Optional[EmailStr] = Field(default=None, description="Optional updated email address")
    role: Optional[UserRole] = Field(default=None, description="Optional updated authorization role")
    is_active: Optional[bool] = Field(default=None, description="Optional updated status of user account")
    clearance_level: Optional[SensitivityLevel] = Field(
        default=None,
        description=(
            "Optional updated confidentiality ceiling (EMPLOYEE role only -- "
            "ADMIN/MANAGER clear everything regardless of this value). "
            "Admin-only, same as role/is_active."
        ),
    )

class PasswordChangeRequest(BaseModel):
    """Pydantic schema for updating current user's password securely."""
    current_password: str = Field(description="The user's current password")
    new_password: str = Field(description="The user's new secure password")

class UserResponse(BaseModel):
    """Pydantic schema for user account details output."""
    id: str = Field(description="Unique user ID")
    company_id: Optional[str] = Field(default=None, description="Owning company (NULL for root)")
    username: str = Field(description="Unique username")
    email: EmailStr = Field(description="Unique email address")
    role: UserRole = Field(description="Assigned authorization role")
    clearance_level: SensitivityLevel = Field(description="Confidentiality ceiling (EMPLOYEE role only).")
    is_active: bool = Field(description="Status of user account")
    is_deleted: bool = Field(description="Soft deletion flag status")

    model_config = {
        "from_attributes": True
    }
