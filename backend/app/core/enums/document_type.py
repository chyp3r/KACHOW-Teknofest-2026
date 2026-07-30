from enum import StrEnum


class DocumentType(StrEnum):
    """Types of incoming official documents (evrak) recognised at intake.

    This taxonomy describes the document the institution *receives*. It is the
    counterpart of `CorrespondenceType`, which describes the official reply the
    institution *produces*. Keeping the two separate lets the intake pipeline
    classify an inbound petition while the drafting pipeline independently
    decides that the answer should be a response letter.
    """

    OFFICIAL_LETTER = "official_letter"
    PETITION = "petition"
    INFORMATION_REQUEST = "information_request"
    COMPLAINT = "complaint"
    CIRCULAR = "circular"
    DIRECTIVE = "directive"
    REPORT = "report"
    MINUTES = "minutes"
    LEAVE_REQUEST = "leave_request"
    OTHER = "other"
