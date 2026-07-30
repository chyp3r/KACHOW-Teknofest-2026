from pydantic import BaseModel, Field

class FeedbackSchema(BaseModel):
    """Skeletal Pydantic schema for feedback."""
    id: str = Field(description="Feedback ID")
    comment: str = Field(description="Feedback comment")
