class SystemModel:
    """Skeletal SQLAlchemy model for system."""
    __tablename__ = "system_logs"
    id: str
    event_name: str
