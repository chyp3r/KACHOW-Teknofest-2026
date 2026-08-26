"""Saf motoru DB yetki deposu ve Redis önbelleğiyle sarmalayan asenkron orkestrasyon.

``engine.authorize`` tek başına yalnızca yerleşik kuralları görür (bkz.
kendi çağıranları ``documents/router.py``/``drafts/router.py``, ki bunlar
hiç ``grants`` geçmez) -- ``permission_grants``'ı gerçekten çözümleyip
etkili kılan katman burasıdır. Bir ``permission_grants`` satırının önemli
olmasına ihtiyaç duyan her şey (yetki yönetiminin kendisi, ve erişim modeli
"rol kuralları artı açık devir" olan gelecekteki her kaynak) çıplak motor
fonksiyonu yerine ``AuthzService`` üzerinden geçer.
"""

from typing import Optional

from app.api.exceptions.authorization import AuthorizationException
from app.core.authz.attributes import Environment, Resource, Subject
from app.core.authz.cache import AuthzDecisionCache
from app.core.authz.engine import Decision, authorize
from app.core.authz.repository import PermissionGrantRepository


class AuthzService:
    """DB ve önbellek destekli ``authorize()``.

    Args:
        grant_repository: Bir öznenin şu anda etkin ``permission_grants``'ını
            çözümler.
        decision_cache: İsteğe bağlı Redis destekli karar önbelleği.
            ``None``, önbelleklemeyi tamamen devre dışı bırakır (her çağrı
            yeniden hesaplar) -- test paketinin autouse fixture'ı tarafından
            kullanılır (bkz. ``tests/conftest.py``); böylece birim testleri
            asla aralarında sızan Redis durumuna bağımlı olmaz.
    """

    def __init__(
        self,
        grant_repository: PermissionGrantRepository,
        decision_cache: Optional[AuthzDecisionCache] = None,
    ):
        self._grants = grant_repository
        self._cache = decision_cache

    async def authorize(
        self,
        subject: Subject,
        action: str,
        resource: Optional[Resource],
        env: Optional[Environment] = None,
    ) -> Decision:
        """``permission_grants``'ı çözümler (önbellek izin verirse) ve karar verir.

        ROOT özneler (``subject.company_id is None``) yetki çözümlemesini
        tamamen atlar -- ``permission_grants`` satırları her zaman şirket
        kapsamlıdır, bu yüzden şirketi olmayan bir özne için bakılacak
        hiçbir şey yoktur. Bir ROOT öznenin kararı yalnızca kiracı kapısı
        ve yerleşik joker karakter kuralından gelir, ``engine.authorize``'ın
        hiç yetki olmadan çağrılmasıyla aynı.
        """
        env = env or Environment()
        resource_type = resource.type if resource is not None else "*"
        resource_id = resource.id if resource is not None else None

        if self._cache is not None and subject.company_id is not None:
            cached = await self._cache.get(
                subject.company_id, subject.user_id, action, resource_type, resource_id
            )
            if cached is not None:
                return cached

        grants = ()
        if subject.company_id is not None:
            grants = await self._grants.list_active_for_subject(
                subject.company_id, subject.role, subject.user_id, action
            )

        decision = authorize(subject, action, resource, env, grants)

        if self._cache is not None and subject.company_id is not None:
            await self._cache.set(
                subject.company_id, subject.user_id, action, resource_type, resource_id, decision
            )

        return decision

    async def invalidate_company(self, company_id: str) -> None:
        """``company_id`` için karar-önbelleği epoch'unu artırır.

        Önbelleklenmiş bir kararın bağlı olabileceği herhangi bir yazma
        işleminden sonra çağırın -- bir ``permission_grants`` satırının
        oluşturulması ya da iptali, bugünün tek yazarı (bkz.
        ``users/router.py``'nin yetki-yönetimi endpoint'leri). Önbellekleme
        devre dışıyken (``self._cache is None``, test varsayılanı -- bkz.
        ``tests/conftest.py``) bir no-op'tur.
        """
        if self._cache is not None:
            await self._cache.bump_epoch(company_id)

    async def authorize_or_raise(
        self,
        subject: Subject,
        action: str,
        resource: Optional[Resource],
        env: Optional[Environment] = None,
    ) -> None:
        """``authorize()``, red durumunda ``AuthorizationException`` fırlatır."""
        decision = await self.authorize(subject, action, resource, env)
        if not decision.permit:
            raise AuthorizationException(message="Bu işlem için yetkiniz yok.")
