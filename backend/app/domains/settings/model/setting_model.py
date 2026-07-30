class SettingModel:
    """Skeletal SQLAlchemy model for settings."""
    __tablename__ = "settings"
    key: str
    value: str
