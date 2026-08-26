"""Dondurulmuş yerleşik rol/eylem kuralları -- PDP'nin temel, DB'den bağımsız katmanı.

``app.ai.policy.schema`` ile aynı desen: bir YAML/JSON kural dosyası yerine
dondurulmuş, versiyonsuz ama içe aktarma-zamanında doğrulanan bir Python
yapısı. Aşağıdaki kurallar yalnızca ``permission_grants`` aracılığıyla daha
özelleştirilir (bkz. ``engine.py``); dağıtım başına asla düzenlenmezler, bu
yüzden dondurulmuş bir demetin zaten bedavaya verdiğinden (yazım hatası
güvenliği, gerçekte değerlendirilenden sapabilecek bir ayrıştırma yolunun
olmaması) bir yapılandırma formatının burada kazandıracağı hiçbir şey yok.

Kiracılık planının ABAC bölümündeki yetki matrisini yansıtır: ROOT
kısıtlamasızdır (onu asıl sınırlayan bu tablo değil, ``engine.authorize``
içindeki kendi kiracı kapısıdır); ADMIN ve MANAGER aşağıdaki her kaynak
türünde şirket geneli (``scope="any"``) hareket eder; EMPLOYEE sahip
olduğu kaynaklarla sınırlıdır (``scope="own"``). Şirket/unit yönetim
eylemlerinin (``unit:manage``, ``user:manage``, ``permission:grant``/
``revoke``) hiç EMPLOYEE kuralı yoktur -- görünüşte "eksik" bir rolün
orada neden sorun olmadığı ama kaynak eylemleri için olduğu için
``check_invariants``'a bakın.
"""

from dataclasses import dataclass

from app.core.enums.user_role import UserRole
from app.core.authz.attributes import Action


@dataclass(frozen=True)
class Rule:
    """Tek bir yerleşik yetki: ``role``, ``scope`` içinde ``action``'ı gerçekleştirebilir.

    Attributes:
        role: Bu kuralın uygulandığı ``UserRole``.
        action: Bir ``Action`` sabiti, ya da ``"*"`` (herhangi bir eylemle
            eşleşir -- yalnızca ``UserRole.ROOT`` için kullanılır).
        scope: ``"any"`` -- şirket genelinde izinli (``engine.authorize``
            içindeki kiracı kapısı yine de uygulanır, bu yüzden bu asla
            şirketler arasına geçmez). ``"own"`` -- yalnızca
            ``resource.owner_id == subject.user_id`` olduğunda izinli.
    """

    role: UserRole
    action: str
    scope: str


#: Bir şirketi yöneten her rolün (ADMIN, MANAGER) şirket genelinde
#: erişebildiği kaynak seviyesi eylemler; EMPLOYEE yalnızca kendisininkine
#: erişir.
_OWNERSHIP_SCOPED_ACTIONS: tuple[str, ...] = (
    Action.DOCUMENT_READ,
    Action.DOCUMENT_UPDATE,
    Action.DOCUMENT_DELETE,
    Action.DRAFT_READ,
    Action.DRAFT_UPDATE,
    Action.DRAFT_DELETE,
    Action.DRAFT_SEND,
    Action.ARTIFACT_TRANSFER,
)

#: Sahiplik kavramı olmayan yönetim eylemleri -- ya şirket geneli ya da hiç.
_MANAGEMENT_ACTIONS: tuple[str, ...] = (
    Action.UNIT_MANAGE,
    Action.USER_MANAGE,
    Action.PERMISSION_GRANT,
    Action.PERMISSION_REVOKE,
)

BUILTIN_RULES: tuple[Rule, ...] = (
    Rule(role=UserRole.ROOT, action="*", scope="any"),
    *(Rule(role=UserRole.ADMIN, action=action, scope="any") for action in _OWNERSHIP_SCOPED_ACTIONS),
    *(Rule(role=UserRole.ADMIN, action=action, scope="any") for action in _MANAGEMENT_ACTIONS),
    *(Rule(role=UserRole.MANAGER, action=action, scope="any") for action in _OWNERSHIP_SCOPED_ACTIONS),
    *(Rule(role=UserRole.MANAGER, action=action, scope="any") for action in _MANAGEMENT_ACTIONS),
    *(Rule(role=UserRole.EMPLOYEE, action=action, scope="own") for action in _OWNERSHIP_SCOPED_ACTIONS),
)


def check_invariants() -> None:
    """ROOT olmayan her rolün en az bir kaynak-kapsamlı kuralı olduğunu doğrular.

    ``app.ai.policy.schema.Policy.check_invariants``'ın
    ``role_clearance_map`` tamlık denetimiyle aynı değişmez biçimi: burada
    atlanmış bir rol bir hatadır (motorun hakkında hiç akıl yürütemediği
    bir rol), kısıtlayıcı bir varsayılan değil -- ROOT muaftır çünkü tek
    joker karakter kuralı zaten her şeyi kapsar.

    Raises:
        ValueError: ADMIN, MANAGER ya da EMPLOYEE'nin sıfır kuralı varsa.
    """
    roles_with_rules = {rule.role for rule in BUILTIN_RULES}
    missing = {UserRole.ADMIN, UserRole.MANAGER, UserRole.EMPLOYEE} - roles_with_rules
    if missing:
        raise ValueError(
            f"authz.rules.BUILTIN_RULES is missing entries for: {sorted(r.value for r in missing)}"
        )


check_invariants()
