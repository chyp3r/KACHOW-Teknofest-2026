from enum import StrEnum


class StepStatus(StrEnum):
    """Outcome of a single plan step or draft revision, as reported over SSE.

    A `StrEnum` member compares and serialises exactly like the bare string
    literal it replaces, so a sub-graph (e.g. draft_graph) that still returns
    plain strings needs no changes to compare equal here.
    """

    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    NEEDS_HUMAN_APPROVAL = "NEEDS_HUMAN_APPROVAL"
    NEEDS_INPUT = "NEEDS_INPUT"
    REVISE_REQUESTED = "REVISE_REQUESTED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
