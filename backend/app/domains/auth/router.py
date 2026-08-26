import logging
from typing import Optional

from fastapi import APIRouter, Depends, Body, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_owner_db
from app.api.responses import APIResponse, SuccessResponse
from app.domains.auth.schema.auth_schema import LoginRequest, TokenResponse, RefreshRequest
from app.domains.users.repository import UserRepository
from app.domains.auth.service import AuthService
from app.api.dependency import oauth2_scheme
from app.infrastructure.cache import get_cache
from app.core.security import decode_token, REFRESH_TOKEN_EXPIRE_DAYS
from app.api.exceptions.authentication import AuthenticationException
from app.api.exceptions.base import BaseAppException
from app.api.rate_limit import rate_limit
import time

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=APIResponse[TokenResponse])
async def login(
    schema: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_owner_db),
    _: None = Depends(rate_limit(max_requests=5, window_seconds=60, key_prefix="auth:login")),
):
    """Kullanıcı kimlik bilgilerini doğrular ve erişim + yenileme jetonu verir.

    Hız sınırı: IP başına dakikada en fazla 5 istek.

    ``get_db`` yerine ``get_owner_db`` kullanılır: ``username``/``email``
    şirket bazında değil, sistem genelinde benzersizdir, bu yüzden çağıranı
    bunlardan biriyle aramak doğası gereği çoklu kiracı (cross-tenant) bir
    işlemdir -- bu çağrı çağıranın kim olduğunu çözene kadar, satır düzeyinde
    bir güvenlik politikasını kapsayacak bir şirket yoktur (bkz.
    ``get_owner_db``'nin kendi docstring'i).
    """
    user_repository = UserRepository(db)
    service = AuthService(user_repository)
    token_response = await service.authenticate_user(schema)
    return SuccessResponse(data=token_response)

@router.post("/refresh", response_model=APIResponse[TokenResponse])
async def refresh(
    schema: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_owner_db),
    _: None = Depends(rate_limit(max_requests=20, window_seconds=60, key_prefix="auth:refresh")),
):
    """Geçerli bir yenileme jetonunu yeni bir erişim + yenileme jetonu çiftiyle değiştirir.

    Hız sınırı: IP başına dakikada en fazla 20 istek.
    Yenileme jetonu şunlara karşı doğrulanır:
    - JWT imzası ve son kullanma tarihi
    - Jeton türü ('access' değil, 'refresh' olmalı)
    - Redis kara listesi (çıkışta geçersiz kılınır)
    - Aktif kullanıcı durumu

    ``get_db`` yerine ``get_owner_db`` kullanılır: bir yenileme jetonu
    ``company_id`` claim'i taşımaz (yalnızca bir erişim jetonu taşır -- bkz.
    ``AuthService.refresh_access_token``), bu yüzden satır düzeyinde bir
    güvenlik politikasını kapsayacak bir kiracı bağlamı henüz mevcut değildir
    (yukarıdaki ``login`` ile aynı gerekçe).
    """
    cache = get_cache()
    if await cache.exists(f"token_blacklist:{schema.refresh_token}"):
        raise AuthenticationException(message="Bu oturum sonlandırıldı. Lütfen tekrar giriş yapın.")

    user_repository = UserRepository(db)
    service = AuthService(user_repository)
    token_response = await service.refresh_access_token(schema.refresh_token)
    return SuccessResponse(data=token_response)

async def _blacklist(cache, token: str, now: float) -> Optional[bool]:
    """Bir jetonu, doğal yaşam süresinin kalanı boyunca kara listeye alır.

    Args:
        cache: Redis önbellek istemcisi.
        token: Kara listeye alınacak ham JWT.
        now: Tek bir çıkış çağrısındaki her iki jeton için paylaşılan geçerli
            epoch zamanı, böylece ikisi de aynı ana göre değerlendirilir.

    Returns:
        Jeton aktifti ve başarıyla kara listeye alındıysa True, aktifti ama
        yazma başarısız olduysa False, jeton çözülemediyse veya zaten süresi
        dolmuşsa None -- iptal edilecek bir şey yoktu, bu bir başarısızlık
        değildir. Çağırana yalnızca bir `False` dönüşü yansıtılmalıdır.
    """
    try:
        payload = decode_token(token)
    except Exception:
        # Bozuk veya süresi zaten dolmuş bir jetonun iptal edilecek aktif bir
        # oturumu yoktur -- burada başarısız olan bir şey yok, yapılacak bir şey yoktu.
        return None
    exp = payload.get("exp")
    if not exp:
        return None
    remaining = int(exp - now)
    if remaining <= 0:
        return None
    # cache.set() asla hata fırlatmaz (bkz. RedisCache.set); dahili olarak
    # loglar ve başarısızlıkta False döner. Bu dönüş değeri, bir kara listeye
    # alma denemesinin başarısız olduğuna dair tek sinyaldi ve eskiden
    # tamamen göz ardı edilirdi -- jeton gerçekten iptal edilmiş olsun ya da
    # olmasın çıkış 200 döndürüyordu, bu yüzden paylaşımlı bir makinede
    # çıkış yapan ve bu sırada bir Redis kesintisi yaşayan bir kullanıcının
    # jetonun hâlâ aktif olduğunu bilme yolu yoktu.
    return await cache.set(f"token_blacklist:{token}", "1", expire_seconds=remaining)


@router.post("/logout", response_model=APIResponse[None])
async def logout(schema: RefreshRequest = Body(default=None), token: str = Depends(oauth2_scheme)):
    """Redis'te hem erişim hem yenileme jetonunu kara listeye alarak mevcut kullanıcının oturumunu kapatır.

    Raises:
        BaseAppException: 500, hâlâ aktif olan bir jeton kara listeye
            alınamazsa -- jeton kullanılabilir durumda kalırken çağırana
            çıkışın başarılı olduğu söylenmemelidir.
    """
    cache = get_cache()
    now = time.time()

    results = []
    if token:
        results.append(("access", await _blacklist(cache, token, now)))
    if schema and schema.refresh_token:
        results.append(("refresh", await _blacklist(cache, schema.refresh_token, now)))

    failed = [kind for kind, ok in results if ok is False]
    if failed:
        logger.error("Logout could not revoke %s token(s); they remain valid until natural expiry.", failed)
        raise BaseAppException(
            message="Çıkış işlemi oturumunuzu tam olarak iptal edemedi. Lütfen tekrar deneyin.",
            error_code="LOGOUT_REVOCATION_FAILED",
            status_code=500,
            details={"unrevoked_tokens": failed},
        )

    return SuccessResponse(data=None)
