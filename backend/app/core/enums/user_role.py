from enum import StrEnum


class UserRole(StrEnum):
    """User role types used throughout the system for RBAC.

    ADMIN and MANAGER both clear every confidentiality level (see
    ``GuardrailPolicy.role_clearance_map``) -- MANAGER represents a company
    manager, trusted with full access the same as ADMIN. EMPLOYEE's ceiling
    is not fixed by role at all: it comes from that individual's own
    ``UserModel.clearance_level``, since two employees can legitimately need
    different access.
    """

    ADMIN = "admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"
