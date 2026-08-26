"""Kimliği doğrulanmış bir kullanıcının etkin gizlilik yetkilendirme seviyesini çözümler.

Rol modeli (bkz. ``UserRole``'ün kendi docstring'i): ADMIN ve MANAGER her
seviyeyi de geçer -- bir şirket yöneticisine, bir admin ile aynı şekilde
tam erişim güvenilir. EMPLOYEE'nin tavanı role göre hiç sabit değildir;
o bireyin kendi ``UserModel.clearance_level``'ından gelir, çünkü iki
çalışanın aynı belge kümesine meşru olarak farklı erişime ihtiyacı olabilir.

Bu modül daha önce boş bir paketti (diskte yalnızca eski bir ``.pyc``, kaynak
kodu yok) -- RBAC katmanı ``GuardrailPolicy.role_clearance_map`` ve
``app.ai.guardrails.output_gate`` en baştan bunun etrafında tasarlandı,
ama şimdiye kadar hiç gerçek bir isteyiciye bağlanmamıştı.
"""

from typing import Optional

from app.ai.policy import get_policy
from app.api.exceptions.authorization import AuthorizationException
from app.core.enums.sensitivity_level import SensitivityLevel
from app.core.enums.user_role import UserRole
from app.domains.users.model.user_model import UserModel


def clearance_for(user: Optional[UserModel]) -> Optional[SensitivityLevel]:
    """Bir kullanıcının gizlilik tavanını çözümler.

    Args:
        user: Kimliği doğrulanmış kullanıcı, ya da kimlik doğrulaması
            yokken ``None`` (``settings.REQUIRE_AUTH`` kapalıyken açık
            demo/dev yolu).

    Returns:
        Kimliği doğrulanmış kullanıcı yoksa ``None`` -- fail-secure
        (güvenli tarafta hata), ``app.ai.guardrails.output_gate.
        evaluate_response``'ın kendi ``requester_clearance`` parametresi
        için zaten belgelediği "bilinmeyen yetkilendirme hiçbir şeyi
        geçmez" varsayılanıyla aynı. Aksi halde çözümlenen seviye:
        ADMIN/MANAGER için politika tavanı, ya da EMPLOYEE için bireysel
        ``user.clearance_level``.
    """
    if user is None:
        return None

    policy = get_policy().guardrail
    try:
        role = UserRole(user.role)
    except ValueError:
        # Tanınmayan bir rol dizesi (veri bozulması, ya da satırları hiç
        # göç ettirilmemiş, enum'dan kaldırılmış bir rol değeri), hata
        # fırlatmak yerine yetkilendirme yok olarak çözümlenir -- bir
        # koruma önlemi araması asla bir isteğin 500 vermesinin nedeni
        # olmamalıdır.
        return None

    if role in (UserRole.ROOT, UserRole.ADMIN, UserRole.MANAGER):
        return policy.role_clearance_map[role]

    try:
        return SensitivityLevel(user.clearance_level)
    except ValueError:
        return policy.role_clearance_map[UserRole.EMPLOYEE]


def bypasses_ownership(user: Optional[UserModel]) -> bool:
    """``user``'ın yalnızca kendi belgelerini değil, *kendi şirketi içindeki*
    her belgeyi görüp görmediği.

    ADMIN/MANAGER/ROOT zaten her gizlilik seviyesini geçer (bkz.
    :func:`clearance_for`) -- kullanıcıyla "şirket yöneticileri her şeye
    erişebilir"in yalnızca yetkilendirmeyi değil sahipliği de kapsadığı
    doğrulandı: önceden var olan sahip başına izolasyon
    (``DocumentRepository.is_owned_by``, ilgisiz "kullanıcı B, kullanıcı
    A'nın belgesine erişemez" IDOR düzeltmesi için eklenmişti) daha önce
    rolden bağımsız olarak tek tip uygulanıyordu, bu yüzden bir admin bile
    şahsen yüklemediği bir belgeyi açamıyordu.

    Çoklu kiracılık çalışmasından bu yana, buradaki "her şey" *sistem
    geneli* değil *şirket geneli* anlamına gelir: bu fonksiyon yalnızca tek
    bir şirket içindeki sahiplik denetiminin atlanıp atlanmadığına karar
    verir. Şirket sınırının kendisi bir katman yukarıda, her repository'nin
    uyguladığı zorunlu ``company_id`` filtresiyle (ve, Faz 3'ten itibaren,
    Postgres RLS ile) uygulanır -- A şirketinin bir MANAGER'ı, bu
    fonksiyonun ne döndürdüğünden bağımsız olarak B şirketinin satırlarına
    asla erişemez. Root, şirketler arasını yalnızca açık kapsam değiştirme
    yolundan (``X-Company-Scope``) okur, asla bu atlama yoluyla değil.

    Args:
        user: Kimliği doğrulanmış kullanıcı, ya da ``None``.

    Returns:
        ADMIN/MANAGER/ROOT için True, aksi halde False (``None``/tanınmayan
        bir rol dahil -- sahiplik izolasyonu fail-secure varsayılandır).
    """
    if user is None:
        return False
    try:
        role = UserRole(user.role)
    except ValueError:
        return False
    return role in (UserRole.ROOT, UserRole.ADMIN, UserRole.MANAGER)


def assert_clearance(user: Optional[UserModel], required_level: SensitivityLevel) -> None:
    """``user``, ``required_level``'ı geçmedikçe hata fırlatır.

    Yetersiz bir yetkilendirmeyi HTTP 403'e dönüştürmesi gereken router
    seviyesi denetimler (``documents/router.py``, ``chat/router.py``) için
    kolaylık sarmalayıcısı -- araç katmanı (``document_tools.py``) ve
    ``output_gate.py`` bunun yerine :func:`clearance_for`'ın sonucunu
    doğrudan karşılaştırır, çünkü bir araç çağrısı hata fırlatmak yerine
    modele bir red dizesi döner.

    Args:
        user: Kimliği doğrulanmış kullanıcı, ya da ``None``.
        required_level: Kaynağın gizlilik seviyesi.

    Raises:
        AuthorizationException: ``user`` ``None`` ise ya da
            ``required_level``'ı geçmiyorsa.
    """
    clearance = clearance_for(user)
    if clearance is None or clearance < required_level:
        raise AuthorizationException(message="Bu içeriği görüntülemek için yeterli yetkiniz yok.")
