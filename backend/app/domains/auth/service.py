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
            raise AuthenticationException(message="Hatalı kullanıcı adı, e-posta veya şifre.")

        if not user.is_active:
            raise AuthenticationException(message="Bu kullanıcı hesabı aktif değil.")

        logger.info(f"Issuing access tokens for authenticated user ID: {user.id}")
        access_token = create_access_token(
            subject=user.id,
            extra_claims={"role": user.role, "username": user.username}
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
            raise AuthenticationException(message="Geçersiz veya süresi dolmuş refresh token.")

        # Ensure it is a refresh token, not an access token
        if payload.get("type") != "refresh":
            raise AuthenticationException(message="Geçersiz token türü. Refresh token bekleniyor.")

        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationException(message="Token içinde geçersiz kullanıcı kimliği.")

        user = await self.user_repository.get_by_id(user_id)
        if not user or not user.is_active:
            raise AuthenticationException(message="Kullanıcı bulunamadı veya hesap aktif değil.")

        logger.info(f"Refreshing access token for user ID: {user.id}")
        new_access_token = create_access_token(
            subject=user.id,
            extra_claims={"role": user.role, "username": user.username}
        )
        new_refresh_token = create_refresh_token(subject=user.id)

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer"
        )
