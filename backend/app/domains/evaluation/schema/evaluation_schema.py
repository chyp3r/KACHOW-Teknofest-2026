from pydantic import BaseModel, Field

class EvaluationSchema(BaseModel):
    """Skeletal Pydantic schema for evaluation."""
    id: str = Field(description="Evaluation ID")
    score: float = Field(description="Evaluation score")
