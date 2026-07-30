from pydantic import BaseModel, Field

class TokenSchema(BaseModel):
    """Skeletal Pydantic schema for authentication token responses."""
    access_token: str = Field(description="Access token string")
    token_type: str = Field(description="Token type, e.g. bearer")
