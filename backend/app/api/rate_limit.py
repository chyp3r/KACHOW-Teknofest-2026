"""FastAPI bağımlılığı olarak Redis destekli kayan pencere (sliding window) hız sınırlayıcı.

Kullanım örneği:
    from app.api.rate_limit import rate_limit

    @router.post("/login")
    async def login(
        schema: LoginRequest,
        _: None = Depends(rate_limit(max_requests=5, window_seconds=60, key_prefix="login")),
    ):
        ...
"""

import logging
import time
from typing import Callable
from uuid import uuid4
from fastapi import Depends, Request

from app.core.config import settings
from app.infrastructure.cache import get_cache
from app.api.exceptions.rate_limit import RateLimitException

logger = logging.getLogger(__name__)


def rate_limit(
    max_requests: int = 10,
    window_seconds: int = 60,
    key_prefix: str = "rate_limit",
) -> Callable:
    """Kayan pencere hız sınırını zorunlu kılan bir FastAPI bağımlılığı döndüren fabrika.

    Args:
        max_requests: Zaman penceresi içinde izin verilen maksimum istek sayısı.
        window_seconds: Kayan pencerenin saniye cinsinden süresi.
        key_prefix: Farklı limitleri ad alanına ayırmak için Redis anahtar öneki.

    Returns:
        Asenkron bir FastAPI bağımlılık fonksiyonu.
    """

    async def _check_rate_limit(request: Request) -> None:
        # X-Forwarded-For yalnızca ekleme yerine üzerine yazan bir proxy'nin
        # arkasında anlamlıdır -- ve yalnızca o zaman güvenlidir. Koşulsuz
        # güvenmek, bir istemcinin istek başına yeni bir başlık ayarlamasına
        # ve hiçbir zaman bir sayaç biriktirmemesine izin verirdi; bkz.
        # core/config.py içindeki TRUST_PROXY_HEADERS'ın docstring'i.
        if settings.TRUST_PROXY_HEADERS and "X-Forwarded-For" in request.headers:
            client_ip = request.headers["X-Forwarded-For"].split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        cache = get_cache()
        redis_key = f"{key_prefix}:{client_ip}"
        now = int(time.time())
        window_start = now - window_seconds
        # ZSET üyesi saniye başına değil, istek başına benzersiz olmalıdır.
        # Mevcut bir üye üzerinde Redis ZADD, ikinci bir giriş eklemek yerine
        # skorunu günceller; bu yüzden çıplak zaman damgasını üye olarak
        # kullanmak aynı saniye içindeki her isteği tek bir isteğe
        # düşürüyordu: bir saniye içinde gönderilen N istek ZCARD=1 olarak
        # skorlanıyordu ve "60 saniyede 5 istek" limiti, fiilen kaç istek
        # geldiğine bakılmaksızın `window_seconds`'tan fazla farklı giriş
        # göremiyordu. Rastgele bir sonek eklemek, skoru (aşağıdaki pencere
        # kırpma işlemi için kullanılır) korurken her üyeyi farklı kılar.
        member = f"{now}:{uuid4().hex}"

        # Kapalı değil, açık yönde başarısız ol (fail open). Hız sınırlama bir
        # koruma mekanizmasıdır, bir doğruluk gereksinimi değil: sayaca
        # erişilemiyorsa bu isteğin limiti aşıp aşmadığını bilemeyiz ve güvenli
        # cevap isteği sunmaktır. Kapalı yönde başarısız olmak, bir Redis
        # yeniden başlatmasının /auth/login, /auth/refresh, /chat/stream,
        # /chat/resume ve /documents/analyze'den 500 döndürmesi anlamına
        # gelirdi -- kullanılamayan bir önbellek her kullanıcıyı sistemin
        # dışında kilitlerdi.
        #
        # Bu ödünleşim gerçektir ve 5/60sn limiti bir kaba kuvvet (brute-force)
        # savunması olan auth:login için en kötüsüdür. Yine de başarısız
        # olunacak doğru taraf budur. Bir saldırgan bu dalı tetikleyemez
        # (önce Redis'i çökertmesi gerekirdi, ve bunu yapabiliyorsa zaten
        # sınırlayıcı açık kapı değildir), oysa Redis'i yeniden başlatan bir
        # operatör bunu her seferinde tetikler.
        try:
            await cache.connect()
            pipe = cache.client.pipeline()
            # Mevcut pencerenin dışındaki sayıları kaldır
            pipe.zremrangebyscore(redis_key, "-inf", window_start)
            # Bu isteği kendi benzersiz üyesi altında kaydet (yukarıya bakın)
            pipe.zadd(redis_key, {member: now})
            # Pencere içindeki istekleri say
            pipe.zcard(redis_key)
            # Anahtarın hareketsizlik sonrası sona ermesi için TTL'yi sıfırla
            pipe.expire(redis_key, window_seconds)
            results = await pipe.execute()
        except Exception:
            logger.warning(
                "Rate limit store unavailable; allowing '%s' through unmetered.",
                key_prefix,
                exc_info=True,
            )
            return

        request_count = results[2]
        if request_count > max_requests:
            raise RateLimitException(
                message=f"Too many requests. Maximum {max_requests} requests per {window_seconds} seconds allowed."
            )

    return _check_rate_limit
