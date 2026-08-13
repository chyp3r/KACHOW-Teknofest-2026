import logging
from app.domains.users.repository import UserRepository
from app.core.security import verify_password, create_access_token, create_refresh_token, decode_token, REFRESH_TOKEN_EXPIRE_DAYS
from app.api.exceptions.authentication import AuthenticationException
from app.domains.auth.schema.auth_schema import LoginRequest, TokenResponse

logger = logging.getLogger(__name__)


class AuthService:
    """SOTA Service to authenticate credentials and issue JWT tokens."""

    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    async def authenticate_user(self, schema: LoginRequest) -> TokenResponse:
        """Authenticate user credentials and return access & refresh JWTs."""
        user = await self.user_repository.get_by_username(schema.username)

        if not user:
            user = await self.user_repository.get_by_email(schema.username)

        if not user or not verify_password(schema.password, user.hashed_password):
            raise AuthenticationException(message="Invalid username, email or password.")

        if not user.is_active:
            raise AuthenticationException(message="This user account is not active.")

        logger.info(f"Issuing access tokens for authenticated user ID: {user.id}")
        access_token = create_access_token(
            subject=user.id,
            extra_claims={"role": user.role, "username": user.username, "company_id": user.company_id}
        )
        refresh_token = create_refresh_token(subject=user.id)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer"
        )

    async def refresh_access_token(self, refresh_token: str) -> TokenResponse:
        """Validate a refresh token and issue a new access token."""
        try:
            payload = decode_token(refresh_token)
        except AuthenticationException:
            raise AuthenticationException(message="Invalid or expired refresh token.")

        # Ensure it is a refresh token, not an access token
        if payload.get("type") != "refresh":
            raise AuthenticationException(message="Invalid token type. Refresh token expected.")

        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationException(message="Invalid user identity in token.")

        user = await self.user_repository.get_by_id(user_id)
        if not user or not user.is_active:
            raise AuthenticationException(message="User not found or account is not active.")

        logger.info(f"Refreshing access token for user ID: {user.id}")
        new_access_token = create_access_token(
            subject=user.id,
            # company_id must match authenticate_user's claim set: as of
            # Faz 3, app.api.middleware.tenant.TenantContextMiddleware reads
            # this claim to set the Postgres GUC row-level security keys
            # off of (see app.infrastructure.database.session.get_db).
            # Omitting it here was harmless before RLS existed -- a token
            # refreshed through this path would silently lose its tenant
            # scope and every subsequent RLS'd read would return zero rows,
            # surfacing as a spurious "User not found" on the very next
            # request.
            extra_claims={"role": user.role, "username": user.username, "company_id": user.company_id}
        )
        new_refresh_token = create_refresh_token(subject=user.id)

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer"
        )
