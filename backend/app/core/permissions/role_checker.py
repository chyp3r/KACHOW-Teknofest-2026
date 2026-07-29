from typing import Sequence

from fastapi import Depends, Request

from app.api.exceptions.authorization import AuthorizationException
from app.core.enums.user_role import UserRole


class RoleChecker:
    """FastAPI bağımlılık olarak kullanılabilen rol tabanlı erişim denetleyicisi.

    Kullanım:
        require_admin = RoleChecker(allowed_roles=[UserRole.ADMIN])

        @router.get("/admin-only", dependencies=[Depends(require_admin)])
        async def admin_endpoint():
            ...
    """

    def __init__(self, allowed_roles: Sequence[UserRole]) -> None:
        self.allowed_roles = list(allowed_roles)

    def __call__(self, request: Request) -> None:
        """İstek nesnesinden kullanıcı rolünü okuyarak yetki kontrolü yapar.

        Not: Bu metod, request.state.user_role değerini okur.
        Gerçek kimlik doğrulama katmanı eklendiğinde bu alan
        JWT payload'ından doldurulacaktır.
        """
        user_role: str | None = getattr(request.state, "user_role", None)

        if user_role is None or user_role not in self.allowed_roles:
            raise AuthorizationException(
                message="Bu kaynağa erişim için yeterli yetkiniz bulunmamaktadır.",
                details={"required_roles": [r.value for r in self.allowed_roles]},
            )
