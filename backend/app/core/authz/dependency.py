"""FastAPI'ye bakan bağlantı katmanı: ``UserModel`` -> ``Subject``, ve PEP #1 dependency fabrikası.

``app.api.dependency``, her router'ın `Depends(...)` çağrılabilirlerini
içe aktardığı tek yer olmaya devam eder (bkz. o modül) -- router'lar bu
paketten doğrudan içe aktarma yapmak yerine ``require_permission`` orada
yeniden dışa aktarılır, diğer tüm dependency fabrikalarıyla aynı şekilde.
"""

from typing import Awaitable, Callable, Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.attributes import Resource, Subject
from app.core.authz.cache import AuthzDecisionCache
from app.core.authz.repository import PermissionGrantRepository
from app.core.authz.service import AuthzService
from app.core.enums.user_role import UserRole
from app.domains.users.model.user_model import UserModel
from app.infrastructure.cache import get_cache
from app.infrastructure.database.session import get_db

#: Bir yetki denetiminin ihtiyaç duyduğu kaynağı, çağıran ve bir DB
#: oturumu verildiğinde yükler. Kaynaksız/oluşturma-zamanı denetimi için
#: ``None`` döner.
ResourceLoader = Callable[[UserModel, AsyncSession], Awaitable[Optional[Resource]]]


def subject_from_user(user: UserModel) -> Subject:
    """PDP'nin ``Subject``'ini kimliği doğrulanmış bir ``UserModel``'den oluşturur.

    Tanınmayan bir ``user.role`` dizesi (veri bozulması, ya da satırları
    hiç göç ettirilmemiş, ``UserRole``'den kaldırılmış bir rol değeri)
    hata fırlatmak yerine ``UserRole.EMPLOYEE``'ye çözümlenir --
    ``app.core.permissions.role_checker.clearance_for``'ın aynı durum için
    yaptığı en-az-yetki-yönünde-hata-toleranslı seçimle aynı: EMPLOYEE'nin
    yerleşik kuralları yalnızca ``scope="own"``'dur, bu yüzden bu asla
    "çağıran, sahip olduğu kaynaklar üzerinde işlem yapabilir"den fazlasını
    vermez, ki bu da motorun kural tablosunun ifade edebileceği en dar
    kapsamdır.
    """
    try:
        role = UserRole(user.role)
    except ValueError:
        role = UserRole.EMPLOYEE
    return Subject(user_id=user.id, role=role, company_id=user.company_id)


def get_authz_service(db: AsyncSession = Depends(get_db)) -> AuthzService:
    """DB ve Redis önbelleği destekli bir ``AuthzService`` sağlar.

    Testlerde (bkz. ``tests/conftest.py``'nin autouse fixture'ı) o an
    geçerli olan ``get_db`` override'ı tarafından desteklenen, önbelleksiz
    bir örnekle geçersiz kılınır; böylece ``permission_grants``'tan hiç
    haberi olmayan bir test, gerçek bir DB gidiş-dönüşü yerine "yetki yok,
    sadece yerleşik kurallar" sonucunu alır.
    """
    return AuthzService(
        grant_repository=PermissionGrantRepository(db),
        decision_cache=AuthzDecisionCache(get_cache()),
    )


def require_permission(action: str, resource_loader: Optional[ResourceLoader] = None):
    """Dependency fabrikası: yalnızca ``authorize()``'ın ``action``'a izin verdiği çağıranları geçirir.

    ``documents/router.py``/``drafts/router.py`` içine gömülü sahiplik
    denetimlerinin (PEP #2, DB yetkileri olmadan çıplak ``engine.authorize``
    kullanır -- bkz. o router'lar) PEP #1 karşılığı. Bu olan, erişim modeli
    tam olarak "yerleşik rol kuralları artı ``permission_grants``'ın
    söyledikleri" olan route'lar içindir, en başta yetki-yönetimi
    endpoint'lerinin kendisi.

    Args:
        action: Bir ``Action`` sabiti.
        resource_loader: Çağıran ve bir DB oturumundan hedef kaynağı
            çözümleyen isteğe bağlı asenkron çağrılabilir. Kaynaksız
            denetimler için atlanır.

    Returns:
        İzin verildiğinde kimliği doğrulanmış kullanıcıyı üreten bir
        FastAPI dependency'si.
    """
    from app.api.dependency import get_current_user

    async def _check(
        current_user: UserModel = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        authz: AuthzService = Depends(get_authz_service),
    ) -> UserModel:
        resource = await resource_loader(current_user, db) if resource_loader is not None else None
        await authz.authorize_or_raise(subject_from_user(current_user), action, resource)
        return current_user

    return _check
