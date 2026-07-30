from pydantic import BaseModel, Field

class UserSchema(BaseModel):
    """Skeletal Pydantic schema for users."""
    id: str = Field(description="User ID")
    username: str = Field(description="Username")
    email: str = Field(description="Email address")
