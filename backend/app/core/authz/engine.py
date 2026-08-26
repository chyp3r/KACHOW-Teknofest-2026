"""Karar algoritması: ``authorize(subject, action, resource, env, grants) -> Decision``.

Tasarım gereği saf ve DB'den bağımsız -- ``app.ai.policy.schema.Policy``'yi
hiçbir şey mock'lamadan tam olarak birim testine tabi tutulabilir kılan
tam olarak aynı özellik, ki bu burada daha da önemli: bu deponun test paketi
ağırlıklı olarak mock tabanlıdır (bkz. ``AGENTS.md``/``tests/conftest.py``),
bu yüzden çalıştırılmak için canlı bir oturuma ya da Redis bağlantısına
ihtiyaç duyan bir karar fonksiyonu yalnızca DB destekli sarmalayıcı
(``app.core.authz.service.AuthzService``) üzerinden test edilebilirdi,
kendi başına değil. ``grants`` zaten çözümlenmiş olarak verilir
(``app.core.authz.repository.PermissionGrantRepository`` DB okumasını
yapar; bunu boş olmayan yetkilerle asıl çağıran ``AuthzService``'tir) bu
yüzden bu modül asla SQLAlchemy ya da Redis içe aktarmaz.

Güvenlik yığınının geri kalanıyla bileşim sırası (kiracılık planından
değişmeden, burada uygulandığı yer olduğu için tekrar belirtilmiştir):

    1. Kiracı kapsamı -- bu fonksiyonun kendi 0. adımı, artı repository
                          katmanının zorunlu ``company_id`` filtresi (ve,
                          gelecekteki bir RLS aşamasından itibaren, Postgres
                          satır güvenliği).
    2. ABAC kararı    -- bu fonksiyon.
    3. Yetkilendirme  -- ``app.core.permissions.role_checker.assert_clearance``,
                          router tarafından ayrıca, *bu karar izin verdikten
                          sonra* çağrılır.
    4. Koruma önlemleri -- ``app.ai.guardrails.output_gate`` /
                          ``app.ai.tools.document_tools``'ın erişimde-red
                          mekanizması.

Yetkilendirme seviyesi bilinçli olarak 2. adıma dahil edilmemiştir:
``app.ai.tools.document_tools`` yetkilendirme seviyesini doğrudan
karşılaştırır ve derlenmiş bir LangGraph düğümü içinden modele bir istisna
değil bir red dizesi döner, ve bu deponun kendi katmanlama kuralına göre
``app.ai.*`` asla ``app.domains.*``'ı içe aktarmaz -- oraya DB destekli bir
PDP çağrısı enjekte etmek bunu ihlal ederdi. Yetkilendirmeyi ayrı, her zaman
uygulanan bir kapı olarak tutmak aynı zamanda bir çağıranın bunu atlatan bir
yetki oluşturamayacağı anlamına da gelir: ``authorize()``'ın bir eylemi
izin vermesi, öznenin bir kaynağın içeriğini kendi yetkilendirme tavanının
üzerinde *okuyabileceği* konusunda hiçbir şey söylemez.
"""

from dataclasses import dataclass
from typing import Optional, Sequence

from app.core.authz.attributes import Resource, Subject, Environment
from app.core.authz.rules import BUILTIN_RULES
from app.core.enums.user_role import UserRole


@dataclass(frozen=True)
class GrantView:
    """Çözümlenmiş, şu anda etkin tek bir ``permission_grants`` satırı.

    Bilinçli olarak SQLAlchemy modelinin kendisi değil -- bu modülü ve
    ``engine.py``'yi her türlü ORM/DB içe aktarımından uzak tutar.
    ``app.core.authz.repository``, bir ``PermissionGrantModel``'in bunlardan
    birine dönüştüğü tek yerdir.

    Attributes:
        id: Yetkinin satır id'si, ``Decision.matched_rule``'da yankılanır;
            böylece izin verilen/reddedilen bir isteğin denetim izi tam
            olarak hangi yetkinin karar verdiğine işaret edebilir.
        subject_type: ``"user"`` ya da ``"role"`` -- ``"unit"``,
            ``unit_memberships`` var olduğunda gelecek bir aşama için
            ayrılmıştır ve bugün çözümlenmiş bir ``GrantView``'de asla
            görünmez.
        subject_id: Bir ``users.id`` (subject_type="user") ya da bir
            ``UserRole`` değeri (subject_type="role").
        action: Bir ``Action`` sabiti, ya da ``"*"``.
        resource_type: Bir ``Resource.type`` değeri, ya da ``"*"``.
        resource_selector: ``{"any": True}`` (``resource_type``'ın her
            kaynağıyla eşleşir), ``{"owner": "self"}`` (yalnızca
            ``resource.owner_id == subject.user_id`` olduğunda eşleşir),
            ya da ``{"id": "..."}`` (yalnızca o tek kaynakla eşleşir).
        effect: ``"permit"`` ya da ``"deny"``.
        priority: Rekabet eden ``permit`` yetkileri arasında daha yüksek
            olan kazanır.
        time_boxed: Yetkinin bir ``valid_from``/``valid_until`` penceresi
            olduğunda True (şu an o pencerenin içinde olsa bile) --
            repository zaten *şu anda etkin* satırlara filtrelemiştir,
            ancak süreli bir yetkinin kararı asla kendi süresinin
            ötesinde önbelleklenmemelidir, bu yüzden ``AuthzService``
            önbelleklenebilirliğe karar vermek için bu bayrağı denetler.
    """

    id: str
    subject_type: str
    subject_id: str
    action: str
    resource_type: str
    resource_selector: dict
    effect: str
    priority: int
    time_boxed: bool = False


@dataclass(frozen=True)
class Decision:
    """Bir ``authorize()`` çağrısının sonucu.

    Attributes:
        permit: Eylemin izinli olup olmadığı.
        reason: Loglarda/denetim izlerinde gösterilmesi güvenli, insan
            tarafından okunabilir açıklama (asla gizli materyal içermez --
            yetkiler zaten hiç sır taşımaz).
        matched_rule: Buna karar veren yerleşik kural (``"<role>:<action>"``)
            ya da ``GrantView.id``, ya da örtük red için ``None`` (hiçbir
            kural ya da yetki eşleşmedi).
        cacheable: ``AuthzService``'in Redis karar önbelleğinde asla
            kalıcı hale getirmemesi gereken kararlar için False -- bir
            kiracı-sınırı reddi (yeniden hesaplaması ucuz, önbelleklemek
            hiçbir şey kazandırmaz) ya da süreli bir yetkiye bağlı bir
            karar (bunu yetkinin kendi süresinin ötesinde önbelleklemek,
            yetki sona erdikten sonra da izin vermeye devam ederdi).
    """

    permit: bool
    reason: str
    matched_rule: Optional[str] = None
    cacheable: bool = True


def role_permitted(role: UserRole, allowed_roles: Sequence[UserRole]) -> bool:
    """``role``'ün ``allowed_roles``'tan biri olup olmadığı.

    ``app.api.dependency.require_roles``'tan çıkarıldı; böylece o dependency
    aynı üyelik denetimini satır içinde yeniden uygulamak yerine bu modülün
    üzerinde ince bir kabuk olur (kiracılık planının ABAC tasarımına göre)
    -- davranış birebir aynı olduğundan, bu çağrıyı yapan hiçbir mevcut
    route ya da test değişmez. Kendisi bir PDP kararı değildir (kiracı/
    sahiplik akıl yürütmesi yoktur): sadece "bu role hiç izin var mı"
    sorusunun motorun geri kalanının yanında yaşayacağı tek bir yer olsun
    diye vardır.
    """
    return role in allowed_roles


def _resource_selector_matches(selector: dict, subject: Subject, resource: Optional[Resource]) -> bool:
    """Bir yetkinin ``resource_selector``'ının ``subject`` için ``resource`` ile eşleşip eşleşmediği."""
    if selector.get("any") is True:
        return True
    if resource is None:
        return False
    owner_selector = selector.get("owner")
    if owner_selector == "self":
        return resource.owner_id == subject.user_id
    id_selector = selector.get("id")
    if id_selector is not None:
        return resource.id == id_selector
    return False


def _grant_matches(grant: GrantView, subject: Subject, action: str, resource: Optional[Resource]) -> bool:
    """``grant``'ın bu ``(subject, action, resource)`` üçlüsüne uygulanıp uygulanmadığı.

    Özne (subject) eşleştirmesi bir katman yukarıda,
    ``app.core.authz.repository.PermissionGrantRepository.list_active_for_subject``
    içinde gerçekleşti (orada bir WHERE ifadesidir, burada tekrarlanmaz) --
    bu yalnızca action ve resource'u yeniden denetler, ki önceden
    çözümlenmiş bir ``GrantView``'in karar verilmesi gereken tek şeyi budur.
    """
    action_matches = grant.action == action or grant.action == "*"
    if not action_matches:
        return False
    if resource is not None:
        type_matches = grant.resource_type == resource.type or grant.resource_type == "*"
        if not type_matches:
            return False
    return _resource_selector_matches(grant.resource_selector, subject, resource)


def authorize(
    subject: Subject,
    action: str,
    resource: Optional[Resource],
    env: Optional[Environment] = None,
    grants: Sequence[GrantView] = (),
) -> Decision:
    """``subject``'in ``resource`` üzerinde ``action``'ı gerçekleştirip gerçekleştiremeyeceğine karar verir.

    Algoritma (bunun yetkilendirme/koruma önlemleriyle aşağı akışta nasıl
    bileşim yaptığı için bu modülün kendi docstring'ine bakın):

        0. Kiracı kapısı: ROOT olmayan bir öznenin kendi şirketi dışındaki
           bir kaynağa dokunması, herhangi bir kural ya da yetki
           danışılmadan doğrudan reddedilir. Bir ROOT özne, yalnızca o
           şirkete açıkça kapsam belirlemişse (``env.company_scope``)
           geçirilir -- kapsam belirlenmemiş bir ROOT'un şirket kaynaklarını
           okuması burada da reddedilir (root'un sistem geneli okuma
           yolları, bu kapıyı tamamen atlayan ``resource=None`` ile özel
           bir ``system:*`` eylemi kullanır).
        1. Eşleşen herhangi bir ``deny`` yetkisi doğrudan kazanır.
        2. Eşleşen ``permit`` yetkileri arasında en yüksek ``priority``
           kazanır.
        3. Aksi halde, yerleşik rol kuralları (``rules.BUILTIN_RULES``)
           karar verir.
        4. Hiçbir kural ya da yetki eşleşmedi: örtük red.

    Args:
        subject: Çağıran.
        action: Bir ``Action`` sabiti.
        resource: Hedef, ya da kaynaksız/oluşturma-zamanı denetimi için
            ``None`` (örn. ``POST /units`` öncesindeki ``unit:manage``,
            ki burada henüz bir ``company_id`` iliştirilecek bir unit
            yoktur -- çağıranın kendi şirketi örtük olarak kapsamdır, bu
            yüzden kiracı kapısının denetleyecek bir şeyi yoktur ve
            atlanır).
        env: İstek-zamanı bağlamı. Varsayılan "şimdi, root kapsam
            değişikliği yok".
        grants: Bu özne ve eylem için önceden çözümlenmiş, şu anda etkin
            yetkiler (bkz. ``GrantView``). Varsayılan olarak boş --
            yalnızca kiracı kapısı + yerleşik kurallara ihtiyaç duyan
            çağıranlar (DB gidiş-dönüşü yok) bunu basitçe atlar.

    Returns:
        Karar.
    """
    if env is None:
        env = Environment()

    if resource is not None and resource.company_id is not None:
        if subject.role == UserRole.ROOT:
            if env.company_scope != resource.company_id:
                return Decision(
                    permit=False,
                    reason="root için şirket kapsamı (X-Company-Scope) ayarlanmamış",
                    cacheable=False,
                )
        elif subject.company_id != resource.company_id:
            return Decision(permit=False, reason="kaynak farklı bir şirkete ait", cacheable=False)

    deny_grants = [g for g in grants if g.effect == "deny" and _grant_matches(g, subject, action, resource)]
    if deny_grants:
        best = max(deny_grants, key=lambda g: g.priority)
        return Decision(
            permit=False,
            reason=f"açık red yetkisi: {best.id}",
            matched_rule=best.id,
            cacheable=not best.time_boxed,
        )

    permit_grants = [
        g for g in grants if g.effect == "permit" and _grant_matches(g, subject, action, resource)
    ]
    if permit_grants:
        best = max(permit_grants, key=lambda g: g.priority)
        return Decision(
            permit=True,
            reason=f"açık izin yetkisi: {best.id}",
            matched_rule=best.id,
            cacheable=not best.time_boxed,
        )

    for rule in BUILTIN_RULES:
        if rule.role != subject.role:
            continue
        if rule.action != action and rule.action != "*":
            continue
        if rule.scope == "any":
            return Decision(permit=True, reason="yerleşik kural (şirket geneli)", matched_rule=f"{rule.role}:{rule.action}")
        if rule.scope == "own" and resource is not None and resource.owner_id == subject.user_id:
            return Decision(permit=True, reason="yerleşik kural (sahiplik)", matched_rule=f"{rule.role}:{rule.action}")

    return Decision(permit=False, reason="eşleşen kural veya yetki yok (örtük red)")
