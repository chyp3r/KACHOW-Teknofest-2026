"""Bir şirketin çalışma zamanı stil adaptörüne okuma/yazma erişimi (Faz C2, #185).

``app.ai.workflows.draft_graph``/``revise_graph`` asla doğrudan
``app.domains``'i import etmez (bkz. ``docs/architecture/backend.md``,
"Backend yalnızca AI Core'u çağırır") -- bu modül yerine bu graph'lara
oluşturma sırasında düz bir async çağrılabilir olarak verilir; yönlendirme
graph'ının ``units_provider``'ı için ``app.domains.units.provider.
get_active_units_for_routing``'in zaten kurduğu tam desen budur. Aynı
nedenle bu graph'lar süreç başına bir kez, herhangi bir istek kapsamlı
``Depends(get_db)`` dışında derlenir: bu modül her çağrı için kendi
kısa ömürlü oturumunu açar (bkz. ``tenant_session``), ``app.domains.
drafts.draft_recorder`` ile aynı şekilde.

Redis'te önbelleklenir (5 dakika TTL), çünkü ``get_company_adapter`` her
tek yazım/revize turunda okunur -- bir admin adaptörü düzenledikten sonra
en fazla 5 dakika boyunca bayat bir okuma, her yazıcı/revize eden
çağrısında Postgres'e gitmeye karşı kabul edilebilir bir ödünleşimdir.
Önbellek hatasında açık başarısız olur (fail open): ``RedisCache``'in
kendi metotları zaten hataları yakalayıp loglar, fırlatmak yerine
``None``/``False`` döner; böylece bir Redis kesintisi bunu "her zaman
Postgres'ten oku"ya düşürür, asla yazım/revize turunun kendisinin sert
bir şekilde başarısız olmasına yol açmaz.
"""

import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import select

from app.ai.adapters.company_adapter import CompanyAdapter
from app.ai.adapters.company_rules import CompanyRule, CompanyRuleSet
from app.ai.identity.company_profile import CompanyProfile
from app.domains.companies.model.company_model import CompanyModel
from app.infrastructure.cache import get_cache
from app.infrastructure.database.session import tenant_session

logger = logging.getLogger(__name__)

#: Bu adaptörün CompanyModel.settings içinde altında yaşadığı anahtar --
#: tek bir anahtarda tutulur ki buradaki bir yazma, settings torbasının
#: geri kalanına (özellik bayrakları, yönlendirme notları) dokunmasın
#: (bkz. set_company_adapter'ın okuma-birleştirme-yazma deseni).
_SETTINGS_KEY = "company_adapter"
_CACHE_TTL_SECONDS = 300
_CACHE_PREFIX = "company_adapter:"


def _cache_key(company_id: str) -> str:
    return f"{_CACHE_PREFIX}{company_id}"


async def get_company_adapter(company_id: str) -> CompanyAdapter:
    """``company_id``'nin mevcut adaptörünü, önce önbellekten olmak üzere döndürür.

    Asla hata fırlatmaz ve asla ``None`` döndürmez -- hiçbir şey
    yapılandırılmamış bir şirket, bilinmeyen bir ``company_id`` veya bir
    Postgres/Redis aksaklığı, hepsi ``CompanyAdapter.empty(company_id)``'e
    çözülür; bu da her çağıranın ``.is_empty`` üzerinden zaten "enjekte
    edilecek bir şey yok" olarak ele aldığı bir değerdir.

    Args:
        company_id: Okunacak kiracı. Falsy ise, önbelleğe veya veritabanına
            dokunmadan boş bir adaptör döner; ``get_active_units_for_routing``
            ile aynı kural.
    """
    if not company_id:
        return CompanyAdapter.empty("")

    cache = get_cache()
    cached = await cache.get(_cache_key(company_id))
    if cached is not None:
        try:
            return CompanyAdapter.from_dict(company_id, json.loads(cached))
        except (json.JSONDecodeError, TypeError):
            logger.warning("Malformed cached company adapter for %s; re-reading.", company_id)

    adapter = await _read_from_db(company_id)
    await cache.set(_cache_key(company_id), json.dumps(adapter.to_dict()), expire_seconds=_CACHE_TTL_SECONDS)
    return adapter


async def _read_from_db(company_id: str) -> CompanyAdapter:
    try:
        async with tenant_session(company_id, is_root=False) as session:
            result = await session.execute(
                select(CompanyModel.settings).where(CompanyModel.id == company_id)
            )
            company_settings = result.scalar_one_or_none()
    except Exception:
        logger.warning("Company adapter DB read failed for %s", company_id, exc_info=True)
        return CompanyAdapter.empty(company_id)
    value = (company_settings or {}).get(_SETTINGS_KEY) if company_settings else None
    return CompanyAdapter.from_dict(company_id, value)


async def set_company_adapter(
    company_id: str,
    *,
    style_rules: Sequence[str] = (),
    preferred_examples: Sequence[str] = (),
    avoided_patterns: Sequence[str] = (),
    sample_count: int = 0,
) -> CompanyAdapter:
    """``company_id``'nin adaptörünü değiştirir ve önbelleği geçersiz kılar.

    Bugün elle çalışan admin endpoint'i tarafından kullanılır
    (``PUT /companies/{id}/adapter`` -- henüz otomatik eğitim yok, bkz.
    #185'in kendi "kapsam dışı" notu); Faz C3'ün eğitim pipeline'ı, o var
    olduğunda 0 yerine gerçek bir ``sample_count`` ile aynı bu fonksiyonu
    çağıracak.

    ``CompanyModel.settings`` üzerinde okuma-birleştirme-yazma: yalnızca
    ``company_adapter`` anahtarına dokunulur, satırda zaten bulunan diğer
    tüm settings anahtarları dokunulmadan kalır.

    Args:
        company_id: Yazılacak kiracı.
        style_rules: Adaptörün tüm kural listesinin yerine geçer (eklenmez).
        preferred_examples: Tüm örnek listesinin yerine geçer.
        avoided_patterns: Tüm kaçınılan-desen listesinin yerine geçer.
        sample_count: Bu sürümü kaç örneğin bilgilendirdiği -- elle yapılan
            bir düzenleme için 0.

    Returns:
        Kalıcı hale getirilen adaptör; ``version`` artırılmış ve
        ``trained_at`` şimdiki zamana ayarlanmış olarak.

    Raises:
        ValueError: ``company_id`` mevcut değilse.
    """
    async with tenant_session(company_id, is_root=False) as session:
        result = await session.execute(select(CompanyModel).where(CompanyModel.id == company_id))
        company = result.scalar_one_or_none()
        if company is None:
            raise ValueError(f"Company '{company_id}' not found.")

        current = CompanyAdapter.from_dict(company_id, (company.settings or {}).get(_SETTINGS_KEY))
        adapter = CompanyAdapter(
            company_id=company_id,
            version=current.version + 1,
            style_rules=tuple(style_rules),
            preferred_examples=tuple(preferred_examples),
            avoided_patterns=tuple(avoided_patterns),
            trained_at=datetime.now(timezone.utc).isoformat(),
            sample_count=sample_count,
        )

        merged_settings = dict(company.settings or {})
        merged_settings[_SETTINGS_KEY] = adapter.to_dict()
        company.settings = merged_settings

    cache = get_cache()
    await cache.delete(_cache_key(company_id))
    return adapter


#: Bir şirketin kimlik profilinin altında yaşadığı anahtar -- _SETTINGS_KEY
#: (company_adapter)'dan ayrı, aynı okuma-birleştirme-yazma/önbellek deseni.
_PROFILE_SETTINGS_KEY = "company_profile"
_PROFILE_CACHE_PREFIX = "company_profile:"

#: `alembic/versions/0010_backfill_tenancy.py`'nin (ve
#: `0015_backfill_recorder_company_id.py`'nin) çoklu kiracılıktan önceki
#: satırlar için bir FK hedefi olarak oluşturduğu sentetik şirketin slug'ı
#: -- gerçek bir kiracı değildir, asla admin tarafından yapılandırılamaz.
#: Onun `CompanyModel.name`'i ("Eski Kayıtlar (Kiracı Öncesi)") aşağıda
#: asla kendini bir `display_name` fallback'i olarak sunmamalıdır: gerçek
#: bir şirketin kendi adının aksine, bu string bir kimliği değil, backfill
#: mekanizmasını adlandırır ve bir taslağın onu asla "bilinen" olarak
#: sunmaması gerekir.
_LEGACY_COMPANY_SLUG = "legacy-pre-tenancy"


def _profile_cache_key(company_id: str) -> str:
    return f"{_PROFILE_CACHE_PREFIX}{company_id}"


async def get_company_profile(company_id: str) -> CompanyProfile:
    """``company_id``'nin mevcut kimlik profilini, önce önbellekten olmak
    üzere döndürür.

    Asla hata fırlatmaz ve asla ``None`` döndürmez -- ``get_company_adapter``
    ile birebir aynıdır.
    """
    if not company_id:
        return CompanyProfile.empty("")

    cache = get_cache()
    cached = await cache.get(_profile_cache_key(company_id))
    if cached is not None:
        try:
            return CompanyProfile.from_dict(company_id, json.loads(cached))
        except (json.JSONDecodeError, TypeError):
            logger.warning("Malformed cached company profile for %s; re-reading.", company_id)

    profile = await _read_profile_from_db(company_id)
    await cache.set(
        _profile_cache_key(company_id),
        json.dumps(profile.to_dict()),
        expire_seconds=_CACHE_TTL_SECONDS,
    )
    return profile


async def _read_profile_from_db(company_id: str) -> CompanyProfile:
    """Bu şirketin profilini okur; hiçbir admin ``display_name``'i hiç
    doldurmamışsa kayıtlı ``CompanyModel.name``'ine geri düşer.

    Bu fallback olmadan, hiç profili yapılandırılmamış bir şirket
    ``CompanyProfile.empty``'e çözülür; bu da onun için ``app.ai.identity.
    parties.SelfParty.is_known``'un False olması demektir: taraf modelinin
    "bu belge bize mi gönderilmiş" diye eşleştirecek bir adı yoktur ve
    yazarın kendi kimlik bölümü hiçbir zaman render edilmez.
    ``companies.name`` her gerçek şirket için oluşturulurken NOT NULL
    olarak ayarlanır, dolayısıyla bu, henüz yapılandırılmamış bir şirket
    için gerçek bir fallback'tir, nadir bir uç durum değil --
    ``display_name``/``short_name``/``letterhead`` vb. boş kalır (bu
    yalnızca eşleştirme/render için bir ad sağlar, asla bir antet veya
    imza sahibi uydurmaz).

    İstisna: sentetik ``_LEGACY_COMPANY_SLUG`` şirketi bu fallback'i asla
    almaz, ne kadar yapılandırılmış bir ``display_name``'e sahip olmasa
    (ve mantıken hiç sahip olamasa) da -- onun ``name``'i bir kimliği
    değil, kendisini oluşturan backfill mekanizmasını tanımlar; onu bir
    kimlikmiş gibi ele almak, ``writing_brief._resolve_yazan_taraf``'ın
    "Eski Kayıtlar (Kiracı Öncesi)"ni kendinden emin, her zaman çözülmüş
    bir gönderen gerçeği olarak sunmasına yol açardı.
    """
    try:
        async with tenant_session(company_id, is_root=False) as session:
            result = await session.execute(
                select(CompanyModel.settings, CompanyModel.name, CompanyModel.slug).where(
                    CompanyModel.id == company_id
                )
            )
            row = result.first()
    except Exception:
        logger.warning("Company profile DB read failed for %s", company_id, exc_info=True)
        return CompanyProfile.empty(company_id)
    if row is None:
        return CompanyProfile.empty(company_id)
    company_settings, company_name, company_slug = row
    value = (company_settings or {}).get(_PROFILE_SETTINGS_KEY) if company_settings else None
    profile = CompanyProfile.from_dict(company_id, value)
    if not profile.display_name and company_name and company_slug != _LEGACY_COMPANY_SLUG:
        profile = replace(profile, display_name=company_name)
    return profile


async def set_company_profile(
    company_id: str,
    *,
    display_name: str = "",
    short_name: str = "",
    agent_name: str = "",
    letterhead: str = "",
    default_signer_title: str = "",
    default_signer_name: str = "",
    aliases: Sequence[str] = (),
) -> CompanyProfile:
    """``company_id``'nin kimlik profilini değiştirir ve önbelleği geçersiz kılar.

    Her alan, profilin mevcut değerinin yerine geçer (kısmi bir patch
    değildir); ``set_company_adapter`` ile aynı "değiştirir, birleştirmez"
    sözleşmesi.

    Raises:
        ValueError: ``company_id`` mevcut değilse.
    """
    async with tenant_session(company_id, is_root=False) as session:
        result = await session.execute(select(CompanyModel).where(CompanyModel.id == company_id))
        company = result.scalar_one_or_none()
        if company is None:
            raise ValueError(f"Company '{company_id}' not found.")

        current = CompanyProfile.from_dict(
            company_id, (company.settings or {}).get(_PROFILE_SETTINGS_KEY)
        )
        profile = CompanyProfile(
            company_id=company_id,
            version=current.version + 1,
            display_name=display_name,
            short_name=short_name,
            agent_name=agent_name,
            letterhead=letterhead,
            default_signer_title=default_signer_title,
            default_signer_name=default_signer_name,
            aliases=tuple(alias for alias in aliases if alias),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        merged_settings = dict(company.settings or {})
        merged_settings[_PROFILE_SETTINGS_KEY] = profile.to_dict()
        company.settings = merged_settings

    cache = get_cache()
    await cache.delete(_profile_cache_key(company_id))
    return profile


#: Bir şirketin zorunlu yazım kurallarının altında yaşadığı anahtar --
#: bilinçli olarak _SETTINGS_KEY (company_adapter)'dan ayrıdır: Faz C3'ün
#: eğitim worker'ı her başarılı çalıştırmada company_adapter'ı topluca
#: yeniden yazar (bkz. set_company_adapter'ın "tüm listenin yerine geçer"
#: sözleşmesi) ve bir adminin burada elle oluşturduğu bir kural, bu yeniden
#: yazmadan dokunulmadan kurtulmalıdır.
_RULES_SETTINGS_KEY = "company_rules"
_RULES_CACHE_PREFIX = "company_rules:"


def _rules_cache_key(company_id: str) -> str:
    return f"{_RULES_CACHE_PREFIX}{company_id}"


async def get_company_rules(company_id: str) -> CompanyRuleSet:
    """``company_id``'nin mevcut zorunlu kural setini, önce önbellekten
    olmak üzere döndürür.

    Asla hata fırlatmaz ve asla ``None`` döndürmez -- ``get_company_adapter``
    ile birebir aynıdır.
    """
    if not company_id:
        return CompanyRuleSet.empty("")

    cache = get_cache()
    cached = await cache.get(_rules_cache_key(company_id))
    if cached is not None:
        try:
            return CompanyRuleSet.from_dict(company_id, json.loads(cached))
        except (json.JSONDecodeError, TypeError):
            logger.warning("Malformed cached company rules for %s; re-reading.", company_id)

    ruleset = await _read_rules_from_db(company_id)
    await cache.set(
        _rules_cache_key(company_id),
        json.dumps(ruleset.to_dict()),
        expire_seconds=_CACHE_TTL_SECONDS,
    )
    return ruleset


async def _read_rules_from_db(company_id: str) -> CompanyRuleSet:
    try:
        async with tenant_session(company_id, is_root=False) as session:
            result = await session.execute(
                select(CompanyModel.settings).where(CompanyModel.id == company_id)
            )
            company_settings = result.scalar_one_or_none()
    except Exception:
        logger.warning("Company rules DB read failed for %s", company_id, exc_info=True)
        return CompanyRuleSet.empty(company_id)
    value = (company_settings or {}).get(_RULES_SETTINGS_KEY) if company_settings else None
    return CompanyRuleSet.from_dict(company_id, value)


async def set_company_rules(company_id: str, *, rules: Sequence[dict[str, Any]]) -> CompanyRuleSet:
    """``company_id``'nin zorunlu kural setini değiştirir ve önbelleği geçersiz kılar.

    Args:
        company_id: Yazılacak kiracı.
        rules: Tam değiştirme kural listesi; her biri ``text`` (zorunlu),
            ``severity`` ("zorunlu"/"onerilen", varsayılan "zorunlu"),
            ``enabled`` (varsayılan True) ve opsiyonel bir ``id`` içeren
            düz bir dict. Zaten bir id taşıyan bir öğe (mevcut bir kuralı
            düzenleyen bir admin) bu id'yi korur; böylece bu düzenlemeden
            önce kaydedilmiş bir hakem kararının kendi
            ``violated_rule_ids``'i hâlâ anlamlı bir şeye işaret eder;
            boş bir id, sunucu tarafından atanan yeni bir id (``K{n}``)
            alır; böylece kuralları kaldıran düzenlemelerde bile id'ler
            hiçbir zaman yeniden kullanılmaz.

    Returns:
        Kalıcı hale getirilen kural seti; ``version`` artırılmış ve
        ``updated_at`` şimdiki zamana ayarlanmış olarak.

    Raises:
        ValueError: ``company_id`` mevcut değilse.
    """
    async with tenant_session(company_id, is_root=False) as session:
        result = await session.execute(select(CompanyModel).where(CompanyModel.id == company_id))
        company = result.scalar_one_or_none()
        if company is None:
            raise ValueError(f"Company '{company_id}' not found.")

        stored = (company.settings or {}).get(_RULES_SETTINGS_KEY) or {}
        current = CompanyRuleSet.from_dict(company_id, stored)
        next_seq = max(int(stored.get("next_id_seq") or 0), len(current.rules))

        built_rules: list[CompanyRule] = []
        for item in rules:
            rule_id = str(item.get("id") or "").strip()
            if not rule_id:
                next_seq += 1
                rule_id = f"K{next_seq}"
            built_rules.append(
                CompanyRule(
                    id=rule_id,
                    text=str(item.get("text") or "").strip(),
                    severity=item.get("severity") or "zorunlu",
                    enabled=bool(item.get("enabled", True)),
                )
            )

        ruleset = CompanyRuleSet(
            company_id=company_id,
            version=current.version + 1,
            rules=tuple(built_rules),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        merged_settings = dict(company.settings or {})
        persisted = ruleset.to_dict()
        # Provider'a özel bir kayıt tutma alanı, CompanyRuleSet'in kendi
        # şeklinin bir parçası değil -- from_dict yalnızca
        # version/rules/updated_at'ı okur, bu yüzden bu ekstra anahtar
        # diğer tüm okuyucular tarafından sessizce yok sayılır.
        persisted["next_id_seq"] = next_seq
        merged_settings[_RULES_SETTINGS_KEY] = persisted
        company.settings = merged_settings

    cache = get_cache()
    await cache.delete(_rules_cache_key(company_id))
    return ruleset


#: Faz C3 Aşama 3 (#191) -- başarılı bir LoRA eğitim çalıştırmasının
#: yayımladığı Ollama model adı (`kachow-{slug}:v{n}`). `_SETTINGS_KEY`'den
#: bilinçli olarak *ayrı* bir settings anahtarıdır, `CompanyAdapter`'a
#: katılmamıştır: bir model override'ı bir altyapı gerçeğidir (bu şirketin
#: çağrılarını hangi ağırlıkların yanıtlayacağı), bir stil tercihi değil,
#: ve ikisi bağımsız olarak ayarlanır -- bir stil-adaptörü çalıştırmasının
#: (Aşama 2) çalışmaya devam etmesi için bir LoRA çalıştırmasının başarılı
#: olması gerekmez, tersi de geçerlidir.
#:
#: Bir gölge (shadow) değerlendirme geçtikten sonra
#: `app.workers.training.run_lora_training_job` tarafından yazılır;
#: **henüz hiçbir yerde tüketilmiyor** -- canlı yazım/revize graph'larını
#: istek başına bir şirketin modelini seçecek şekilde bağlamak, ayrı ve
#: daha büyük bir değişikliktir (süreç başına bir kez yerine model başına
#: bir graph oluşturmak/önbelleklemek) ve bilinçli olarak #191'in kapsamı
#: dışında bırakılmıştır. Bu bağlantı kurulduğunda bu değeri okuyun.
_MODEL_OVERRIDE_KEY = "llm_model_override"


async def get_llm_model_override(company_id: str) -> Optional[str]:
    """Gölge değerlendirmesini geçmiş bir LoRA adaptörünün ``company_id``
    için yayımladığı Ollama model adı, ya da hiç eğitmemişse (yaygın durum
    -- çağıranlar ``settings.OLLAMA_MODEL``'e geri düşmelidir) ``None``."""
    if not company_id:
        return None
    try:
        async with tenant_session(company_id, is_root=False) as session:
            result = await session.execute(
                select(CompanyModel.settings).where(CompanyModel.id == company_id)
            )
            company_settings = result.scalar_one_or_none()
    except Exception:
        logger.warning("LLM model override read failed for %s", company_id, exc_info=True)
        return None
    return (company_settings or {}).get(_MODEL_OVERRIDE_KEY) if company_settings else None


async def set_llm_model_override(company_id: str, model_name: str) -> None:
    """``model_name``'i ``company_id``'nin override'ı olarak kaydeder;
    ``set_company_adapter`` ile aynı şekilde ``CompanyModel.settings``
    üzerinde okuma-birleştirme-yazma.

    Raises:
        ValueError: ``company_id`` mevcut değilse.
    """
    async with tenant_session(company_id, is_root=False) as session:
        result = await session.execute(select(CompanyModel).where(CompanyModel.id == company_id))
        company = result.scalar_one_or_none()
        if company is None:
            raise ValueError(f"Company '{company_id}' not found.")
        merged_settings = dict(company.settings or {})
        merged_settings[_MODEL_OVERRIDE_KEY] = model_name
        company.settings = merged_settings
