from enum import StrEnum


class ReasoningLevel(StrEnum):
    """Speed-vs-quality tradeoff requested for a single AI request."""

    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"
