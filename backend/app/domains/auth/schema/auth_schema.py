from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    """Pydantic schema for credentials validation on login."""
    username: str = Field(description="Username or Email address of user")
    password: str = Field(description="Raw account password")

class TokenResponse(BaseModel):
    """Pydantic schema for token response payload."""
    access_token: str = Field(description="JWT Access Token")
    refresh_token: str = Field(description="JWT Refresh Token")
    token_type: str = Field(default="bearer", description="Token type prefix")

class RefreshRequest(BaseModel):
    """Pydantic schema for access token renewal via refresh token."""
    refresh_token: str = Field(description="Long-lived JWT Refresh Token")
