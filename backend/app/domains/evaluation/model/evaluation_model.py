class EvaluationModel:
    """Skeletal SQLAlchemy model for evaluation."""
    __tablename__ = "evaluations"
    id: str
    score: float
