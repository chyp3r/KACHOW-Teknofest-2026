from enum import StrEnum


class UserRole(StrEnum):
    """User role types used throughout the system for RBAC."""

    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
