from pydantic import BaseModel, Field

class SystemLogSchema(BaseModel):
    """Skeletal Pydantic schema for system log."""
    id: str = Field(description="Log ID")
    event_name: str = Field(description="Event name")
