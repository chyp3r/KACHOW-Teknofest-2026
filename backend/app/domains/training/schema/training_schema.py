from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TrainingSampleResponse(BaseModel):
    """Derlenmiş bir tercih-çifti örneği için Pydantic şeması."""

    model_config = {"from_attributes": True}

    id: str
    training_run_id: Optional[str] = None
    source: str
    source_feedback_id: Optional[str] = None
    source_draft_id: Optional[str] = None
    prompt_context: Optional[str] = None
    chosen: Optional[str] = None
    rejected: Optional[str] = None
    weight: float
    created_at: datetime
    updated_at: datetime


class TrainingSampleStatsResponse(BaseModel):
    """`GET /companies/{id}/training-samples/stats` için Pydantic şeması."""

    total: int
    by_source: dict[str, int]
    min_samples_required: int
    samples_remaining_to_threshold: int


class TrainingRunResponse(BaseModel):
    """Bir eğitim çalıştırması için Pydantic şeması."""

    model_config = {"from_attributes": True}

    id: str
    kind: str
    status: str
    trigger: str
    sample_count: Optional[int] = None
    metrics: Optional[dict] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
