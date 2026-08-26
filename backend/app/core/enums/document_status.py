from enum import StrEnum


class DocumentStatus(StrEnum):
    """Bir belgenin AI işleme boru hattı boyunca yaşam döngüsü durumları."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"
