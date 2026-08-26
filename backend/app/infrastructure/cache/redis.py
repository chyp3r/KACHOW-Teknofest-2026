import logging
from typing import Any, Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class RedisCache:
    """Güncel eşzamansız Redis Cache istemci sarmalayıcısı."""

    def __init__(self, redis_url: str):
        """Redis Cache sarmalayıcısını başlat.

        Args:
            redis_url: Bağlantı dizesi (örn. "redis://localhost:6379/0").
        """
        self.redis_url = redis_url
        self.client: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        """Henüz bağlı değilse Redis'e eşzamansız bağlantı kur."""
        if self.client is None:
            self.client = aioredis.from_url(
                self.redis_url, decode_responses=True
            )
            logger.info(f"Connected to Redis at {self.redis_url}")

    async def close(self) -> None:
        """Redis bağlantı havuzunu kapat."""
        if self.client is not None:
            # .close(), bu redis-py sürümünde .aclose() için eski (deprecated)
            # bir takma addır ve her çağrıda bir DeprecationWarning yayar.
            await self.client.aclose()
            self.client = None
            logger.info("Closed Redis cache connection.")

    async def get(self, key: str) -> Optional[str]:
        """Önbellekten anahtara göre bir değer al."""
        await self.connect()
        try:
            return await self.client.get(key)
        except Exception as e:
            logger.error(f"Redis get failed for key={key}: {e}")
            return None

    async def set(
        self, key: str, value: str, expire_seconds: Optional[int] = None
    ) -> bool:
        """İsteğe bağlı TTL ile önbelleğe bir değer ayarla."""
        await self.connect()
        try:
            await self.client.set(key, value, ex=expire_seconds)
            return True
        except Exception as e:
            logger.error(f"Redis set failed for key={key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Önbellekten bir anahtarı sil."""
        await self.connect()
        try:
            result = await self.client.delete(key)
            return result > 0
        except Exception as e:
            logger.error(f"Redis delete failed for key={key}: {e}")
            return False

    async def incr(self, key: str) -> Optional[int]:
        """Bir anahtarı atomik olarak artır (yoksa 1'de oluştur) ve yeni değeri döndür.

        Epoch-artırma önbellek geçersizleştirmesi için kullanılır (bkz.
        ``app.core.authz.cache.AuthzDecisionCache``): bir namespace'in
        epoch sayacını artırmak O(1)'dir ve başka hiçbir şeye dokunmaz;
        o namespace altındaki her önbelleklenmiş karar anahtarını tarayıp
        silmenin aksine.
        """
        await self.connect()
        try:
            return await self.client.incr(key)
        except Exception as e:
            logger.error(f"Redis incr failed for key={key}: {e}")
            return None

    async def publish(self, channel: str, message: str) -> None:
        """Bir Redis pub/sub kanalına mesaj yayınla.

        Bildirim akışının dağıtımı için kullanılır (bkz.
        ``app.domains.notifications.router``'ın SSE uç noktası): birden
        fazla uvicorn worker'ı çalıştığında süreç geneli bellek içi
        ``EventBus`` tek başına yeterli değildir, çünkü worker A'ya bağlı
        bir abone, worker B'den yayınlanan bir olayı asla görmez. Buradaki
        diğer her metod gibi açık başarısız olur -- düşürülen bir canlı-
        push bildirimi hâlâ ``notifications``'ta bir satır olarak var olur
        ve bir sonraki ``GET /notifications`` sorgusunda görünür, bu yüzden
        bir Redis aksaklığı "daha az gerçek zamanlı"ya düşer, asla veri
        kaybına değil.
        """
        await self.connect()
        try:
            await self.client.publish(channel, message)
        except Exception as e:
            logger.error(f"Redis publish failed for channel={channel}: {e}")

    async def exists(self, key: str) -> bool:
        """Bir anahtarın önbellekte var olup olmadığını kontrol et."""
        await self.connect()
        try:
            result = await self.client.exists(key)
            return result > 0
        except Exception as e:
            logger.error(f"Redis exists check failed for key={key}: {e}")
            return False

    async def clear(self) -> bool:
        """Veritabanı anahtarlarını temizle."""
        await self.connect()
        try:
            await self.client.flushdb()
            logger.warning("Redis cache database cleared/flushed.")
            return True
        except Exception as e:
            logger.error(f"Redis clear failed: {e}")
            return False
