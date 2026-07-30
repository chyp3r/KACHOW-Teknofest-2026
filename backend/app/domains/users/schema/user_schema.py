from pydantic import BaseModel, EmailStr, Field
from app.core.enums.user_role import UserRole

class UserCreate(BaseModel):
    """Pydantic schema for creating a new user account."""
    username: str = Field(description="Unique username")
    email: EmailStr = Field(description="Unique email address")
    password: str = Field(description="Plain text password")
    role: UserRole = Field(default=UserRole.EMPLOYEE, description="Assigned role for authorization")

class UserResponse(BaseModel):
    """Pydantic schema for user account details output."""
    id: str = Field(description="Unique user ID")
    username: str = Field(description="Unique username")
    email: EmailStr = Field(description="Unique email address")
    role: UserRole = Field(description="Assigned authorization role")
    is_active: bool = Field(description="Status of user account")

    model_config = {
        "from_attributes": True
    }
