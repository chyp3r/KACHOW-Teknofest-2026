from pydantic import BaseModel, Field

class SettingSchema(BaseModel):
    """Skeletal Pydantic schema for settings."""
    key: str = Field(description="Setting key")
    value: str = Field(description="Setting value")
