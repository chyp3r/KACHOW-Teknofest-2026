from enum import StrEnum


class ComplianceStatus(StrEnum):
    """Result of checking an incoming document against required-field rules.

    Derived deterministically from the set of missing fields, never from a model
    judgement: `COMPLIANT` when nothing is missing, `INCOMPLETE` when at least one
    mandatory field is absent, and `PARTIALLY_COMPLIANT` when only advisory
    fields are absent.
    """

    COMPLIANT = "compliant"
    PARTIALLY_COMPLIANT = "partially_compliant"
    INCOMPLETE = "incomplete"
