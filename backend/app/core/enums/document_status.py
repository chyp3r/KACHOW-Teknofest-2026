from enum import StrEnum


class DocumentStatus(StrEnum):
    """Lifecycle states of a document through the AI processing pipeline."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"
