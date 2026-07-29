from typing import Sequence

from fastapi import Request

from app.api.exceptions.authorization import AuthorizationException
from app.core.enums.user_role import UserRole


class RoleChecker:
    """FastAPI dependency for role-based access control (RBAC).

    Usage:
        require_admin = RoleChecker(allowed_roles=[UserRole.ADMIN])

        @router.get("/admin-only", dependencies=[Depends(require_admin)])
        async def admin_endpoint():
            ...
    """

    def __init__(self, allowed_roles: Sequence[UserRole]) -> None:
        """Initialize RoleChecker with the set of permitted roles.

        Args:
            allowed_roles: Roles that are granted access to the protected resource.
        """
        self.allowed_roles = list(allowed_roles)

    def __call__(self, request: Request) -> None:
        """Enforce role authorization by reading user_role from request state.

        The authentication middleware is responsible for populating
        request.state.user_role from the decoded JWT payload.

        Args:
            request: The incoming FastAPI/Starlette request object.

        Raises:
            AuthorizationException: If the role is missing or not in allowed_roles.
        """
        user_role: str | None = getattr(request.state, "user_role", None)

        if user_role is None or user_role not in self.allowed_roles:
            raise AuthorizationException(
                message="You do not have permission to access this resource.",
                details={"required_roles": [r.value for r in self.allowed_roles]},
            )
