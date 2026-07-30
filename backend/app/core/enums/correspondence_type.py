from enum import StrEnum


class CorrespondenceType(StrEnum):
    """Supported official correspondence outputs produced by the draft workflow."""

    COVER_LETTER = "cover_letter"
    RESPONSE_LETTER = "response_letter"
    INFORMATION_NOTICE = "information_notice"
    OTHER_OFFICIAL = "other_official"
