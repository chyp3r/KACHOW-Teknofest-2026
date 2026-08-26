import logging
from app.domains.users.repository import UserRepository
from app.core.security import verify_password, create_access_token, create_refresh_token, decode_token, REFRESH_TOKEN_EXPIRE_DAYS
from app.api.exceptions.authentication import AuthenticationException
from app.domains.auth.schema.auth_schema import LoginRequest, TokenResponse

logger = logging.getLogger(__name__)


class AuthService:
    """Kimlik bilgilerini doğrulayan ve JWT token'ları veren SOTA servis."""

    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    async def authenticate_user(self, schema: LoginRequest) -> TokenResponse:
        """Kullanıcı kimlik bilgilerini doğrular ve access & refresh JWT'lerini döndürür."""
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
        """Bir refresh token'ı doğrular ve yeni bir access token verir."""
        try:
            payload = decode_token(refresh_token)
        except AuthenticationException:
            raise AuthenticationException(message="Invalid or expired refresh token.")

        # Bunun bir access token değil, refresh token olduğundan emin ol
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
            # company_id, authenticate_user'ın claim kümesiyle eşleşmelidir: Faz 3
            # itibarıyla app.api.middleware.tenant.TenantContextMiddleware, Postgres
            # GUC satır düzeyi güvenlik (row-level security) anahtarlarını
            # ayarlamak için bu claim'i okur (bkz. app.infrastructure.database.session.get_db).
            # RLS mevcut olmadan önce burada bu claim'i atlamak zararsızdı -- bu yol
            # üzerinden yenilenen bir token, tenant kapsamını sessizce kaybeder ve
            # sonraki her RLS'li okuma sıfır satır döndürür; bu da bir sonraki
            # istekte sahte bir "Kullanıcı bulunamadı" hatası olarak ortaya çıkar.
            extra_claims={"role": user.role, "username": user.username, "company_id": user.company_id}
        )
        new_refresh_token = create_refresh_token(subject=user.id)

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer"
        )
