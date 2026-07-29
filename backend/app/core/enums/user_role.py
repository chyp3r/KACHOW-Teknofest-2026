from enum import StrEnum


class UserRole(StrEnum):
    """Sistemdeki kullanıcı rol türleri."""

    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
