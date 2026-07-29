from enum import StrEnum


class DocumentStatus(StrEnum):
    """Belge işlem yaşam döngüsü durumları."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"
