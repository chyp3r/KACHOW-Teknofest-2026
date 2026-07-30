from pydantic import BaseModel, Field

class ChatSessionSchema(BaseModel):
    """Skeletal Pydantic schema for chat session."""
    id: str = Field(description="Chat session ID")
