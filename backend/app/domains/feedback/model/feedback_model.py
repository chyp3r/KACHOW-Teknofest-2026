class FeedbackModel:
    """Skeletal SQLAlchemy model for feedback."""
    __tablename__ = "feedbacks"
    id: str
    comment: str
