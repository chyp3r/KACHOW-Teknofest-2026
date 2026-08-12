from enum import StrEnum


class CorrespondenceType(StrEnum):
    """Supported official correspondence outputs produced by the draft workflow.

    Fixed at these four per spec. A user request for a specific genre that
    isn't one of them (an itiraz dilekçesi, a muvafakatname, ...) still
    resolves here -- to OTHER_OFFICIAL -- but carries the genre itself as a
    separate free-text sub-genre alongside the type (see
    ``app.ai.workflows.correspondence.resolve_correspondence_type``), so the
    writer prompt still knows what to actually produce.
    """

    COVER_LETTER = "cover_letter"
    RESPONSE_LETTER = "response_letter"
    INFORMATION_NOTICE = "information_notice"
    OTHER_OFFICIAL = "other_official"
