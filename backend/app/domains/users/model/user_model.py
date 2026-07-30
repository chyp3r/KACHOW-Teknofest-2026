class UserModel:
    """Skeletal SQLAlchemy model for users."""
    __tablename__ = "users"
    id: str
    username: str
    email: str
