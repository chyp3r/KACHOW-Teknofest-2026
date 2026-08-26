from enum import StrEnum


class ReasoningLevel(StrEnum):
    """Tek bir AI isteği için talep edilen hız-kalite takası."""

    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"
