"""``authorize()`` kararları için epoch tabanlı geçersizleştirme kullanan Redis önbelleği.

Kiracılık planından gelen temel tasarım kısıtı: geçersizleştirme bir epoch
artırımıdır (``INCR authz:epoch:{company_id}``), asla bir ``SCAN``/``DEL``
taraması değildir. Çok işçili (multi-worker) bir uvicorn dağıtımı tek bir
Redis'i paylaşır ve bir kararın kendi anahtarı, hesaplandığı epoch'u zaten
içerir -- epoch'u artırmak, o şirket için önceden önbelleklenmiş her kararı
erişilemez hale getirir (bir sonraki arama yeni epoch altındaki bir anahtarı
sorar, ki bu bir önbellek ıskasıdır) ve eski anahtarlara hiç dokunmadan,
onlar kendi TTL'lerinde kendiliğinden sona erer.

Redis hatalarında fail-open (açık kalarak hataya toleranslı davranış):
bir önbellek ıskası (gerçek ya da erişilemeyen bir Redis'ten kaynaklanan)
sadece ``AuthzService``'in ``engine.authorize`` üzerinden yeniden hesaplama
yapması anlamına gelir -- daha yavaş, ama asla yanlış değil.
``app.infrastructure.cache.redis.RedisCache`` tam da bu sebeple kendi
istisnalarını zaten yutar ve loglar (bkz. modül docstring'inin komşuları,
örn. ``app.api.rate_limit``'in bilinçli olarak fail-open olması); bu modül
bunun üzerine ekstra bir try/except eklemez çünkü bu sınırın ötesinde
fırlatabilecek başka bir şey kalmamıştır.
"""

import json
import logging
from dataclasses import asdict
from typing import Optional

from app.core.authz.engine import Decision
from app.infrastructure.cache.redis import RedisCache

logger = logging.getLogger(__name__)

_DECISION_TTL_SECONDS = 60


def _epoch_key(company_id: str) -> str:
    return f"authz:epoch:{company_id}"


def _decision_key(
    company_id: str, epoch: int, user_id: str, action: str, resource_type: str, resource_id: Optional[str]
) -> str:
    return f"authz:d:{company_id}:{epoch}:{user_id}:{action}:{resource_type}:{resource_id or '-'}"


class AuthzDecisionCache:
    """``RedisCache``'i epoch-anahtar şeması ve ``Decision`` (de)serileştirmesiyle sarmalar."""

    def __init__(self, cache: RedisCache):
        self._cache = cache

    async def current_epoch(self, company_id: str) -> int:
        """``company_id`` için etkin epoch. Ayarlanmamışsa ``0`` döner (yeni bir şirket,
        ya da bir Redis ıskası/hatası -- her iki durumda da epoch ``0`` diğerleri kadar
        geçerli bir ad alanıdır, sadece boş başlar)."""
        raw = await self._cache.get(_epoch_key(company_id))
        if raw is None:
            return 0
        try:
            return int(raw)
        except ValueError:
            return 0

    async def bump_epoch(self, company_id: str) -> None:
        """``company_id`` için önbelleklenmiş her kararı geçersiz kıl.

        Bu, önbelleklenmiş bir kararın bağlı olabileceği herhangi bir yazma
        işleminde çağrılmalıdır: bir ``permission_grants`` satırının
        oluşturulması/iptali, ya da (bu alanlar bu sistem üzerinden
        değiştirilebilir hale geldiğinde) bir kullanıcının rolü ya da
        yetkilendirme seviyesi.
        """
        result = await self._cache.incr(_epoch_key(company_id))
        if result is None:
            logger.warning("authz epoch bump failed for company_id=%s (Redis unavailable)", company_id)

    async def get(
        self, company_id: str, user_id: str, action: str, resource_type: str, resource_id: Optional[str]
    ) -> Optional[Decision]:
        epoch = await self.current_epoch(company_id)
        raw = await self._cache.get(
            _decision_key(company_id, epoch, user_id, action, resource_type, resource_id)
        )
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return Decision(**payload)

    async def set(
        self,
        company_id: str,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: Optional[str],
        decision: Decision,
    ) -> None:
        if not decision.cacheable:
            return
        epoch = await self.current_epoch(company_id)
        key = _decision_key(company_id, epoch, user_id, action, resource_type, resource_id)
        await self._cache.set(key, json.dumps(asdict(decision)), expire_seconds=_DECISION_TTL_SECONDS)
