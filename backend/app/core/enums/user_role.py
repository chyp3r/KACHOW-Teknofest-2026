from enum import StrEnum


class UserRole(StrEnum):
    """User role types used throughout the system for RBAC.

    Four roles, one per level of the tenancy hierarchy:

    - ROOT: platform operator, not bound to any company (``UserModel.
      company_id`` is NULL only for this role). Sees every company, never a
      company's business data directly -- see ``app.core.authz`` for how a
      root subject must explicitly scope to a company before any
      company-resource action is permitted.
    - ADMIN: a company admin, created by root, scoped to exactly one
      company.
    - MANAGER: a company manager, designated by that company's admin.
    - EMPLOYEE: a company employee, designated by an admin or manager.

    ROOT, ADMIN and MANAGER all clear every confidentiality level (see
    ``GuardrailPolicy.role_clearance_map``) -- MANAGER represents a company
    manager, trusted with full access the same as ADMIN. EMPLOYEE's ceiling
    is not fixed by role at all: it comes from that individual's own
    ``UserModel.clearance_level``, since two employees can legitimately need
    different access.
    """

    ROOT = "root"
    ADMIN = "admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"
