"""Read/write access to a company's runtime style adapter (Faz C2, #185).

``app.ai.workflows.draft_graph``/``revise_graph`` never import
``app.domains`` directly (see ``docs/architecture/backend.md``, "Backend
yalnızca AI Core'u çağırır") -- this module is handed to those graphs as a
plain async callable at construction time instead, the exact pattern
``app.domains.units.provider.get_active_units_for_routing`` already
established for the routing graph's ``units_provider``. Same reason those
graphs are compiled once per process outside any request-scoped
``Depends(get_db)``: this opens its own short-lived session per call (see
``tenant_session``), same as ``app.domains.drafts.draft_recorder``.

Redis-cached (5 minute TTL) since ``get_company_adapter`` is read on every
single draft/revise turn -- a stale read for up to 5 minutes after an admin
edits the adapter is an acceptable tradeoff against hitting Postgres on
every writer/reviser call. Fails open on a cache error: ``RedisCache``'s own
methods already catch and log, returning ``None``/``False`` rather than
raising, so a Redis outage degrades this to "always read from Postgres,"
never to a hard failure of the draft/revise turn itself.
"""

import json
import logging
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

#: The key this adapter lives under inside CompanyModel.settings -- kept to
#: one key so the rest of the settings bag (feature flags, routing notes)
#: is untouched by a write here (see set_company_adapter's read-merge-write).
_SETTINGS_KEY = "company_adapter"
_CACHE_TTL_SECONDS = 300
_CACHE_PREFIX = "company_adapter:"


def _cache_key(company_id: str) -> str:
    return f"{_CACHE_PREFIX}{company_id}"


async def get_company_adapter(company_id: str) -> CompanyAdapter:
    """Return ``company_id``'s current adapter, cache-first.

    Never raises and never returns ``None`` -- a company with nothing
    configured, an unknown ``company_id``, or a Postgres/Redis hiccup all
    resolve to ``CompanyAdapter.empty(company_id)``, which every caller
    already treats as "nothing to inject" via ``.is_empty``.

    Args:
        company_id: The tenant to read. Falsy returns an empty adapter
            without touching cache or the database, same convention as
            ``get_active_units_for_routing``.
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
    """Replace ``company_id``'s adapter and invalidate the cache.

    Used today by the manual admin endpoint (``PUT /companies/{id}/adapter``
    -- there is no automated training yet, see #185's own "kapsam dışı"
    note); Faz C3's training pipeline will call this same function once it
    exists, with a real ``sample_count`` instead of 0.

    Read-merge-write on ``CompanyModel.settings``: only the
    ``company_adapter`` key is touched, every other settings key already on
    the row survives untouched.

    Args:
        company_id: The tenant to write.
        style_rules: Replaces the adapter's entire rule list (not appended).
        preferred_examples: Replaces the entire example list.
        avoided_patterns: Replaces the entire avoided-pattern list.
        sample_count: How many samples informed this version -- 0 for a
            hand-authored edit.

    Returns:
        The persisted adapter, with ``version`` bumped and ``trained_at``
        set to now.

    Raises:
        ValueError: If ``company_id`` doesn't exist.
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


#: The key a company's identity profile lives under -- separate from
#: _SETTINGS_KEY (company_adapter), same read-merge-write/cache pattern.
_PROFILE_SETTINGS_KEY = "company_profile"
_PROFILE_CACHE_PREFIX = "company_profile:"


def _profile_cache_key(company_id: str) -> str:
    return f"{_PROFILE_CACHE_PREFIX}{company_id}"


async def get_company_profile(company_id: str) -> CompanyProfile:
    """Return ``company_id``'s current identity profile, cache-first.

    Never raises and never returns ``None`` -- mirrors
    ``get_company_adapter`` exactly.
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
    try:
        async with tenant_session(company_id, is_root=False) as session:
            result = await session.execute(
                select(CompanyModel.settings).where(CompanyModel.id == company_id)
            )
            company_settings = result.scalar_one_or_none()
    except Exception:
        logger.warning("Company profile DB read failed for %s", company_id, exc_info=True)
        return CompanyProfile.empty(company_id)
    value = (company_settings or {}).get(_PROFILE_SETTINGS_KEY) if company_settings else None
    return CompanyProfile.from_dict(company_id, value)


async def set_company_profile(
    company_id: str,
    *,
    display_name: str = "",
    short_name: str = "",
    agent_name: str = "",
    letterhead: str = "",
    default_signer_title: str = "",
) -> CompanyProfile:
    """Replace ``company_id``'s identity profile and invalidate the cache.

    Every field replaces the profile's current value (not a partial patch),
    same "replaces, does not merge" contract as ``set_company_adapter``.

    Raises:
        ValueError: If ``company_id`` doesn't exist.
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
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        merged_settings = dict(company.settings or {})
        merged_settings[_PROFILE_SETTINGS_KEY] = profile.to_dict()
        company.settings = merged_settings

    cache = get_cache()
    await cache.delete(_profile_cache_key(company_id))
    return profile


#: The key a company's mandatory drafting rules live under -- deliberately
#: separate from _SETTINGS_KEY (company_adapter): Faz C3's training worker
#: rewrites company_adapter wholesale on every successful run (see
#: set_company_adapter's "replaces the whole list" contract), and a rule an
#: admin hand-authored here must survive that rewrite untouched.
_RULES_SETTINGS_KEY = "company_rules"
_RULES_CACHE_PREFIX = "company_rules:"


def _rules_cache_key(company_id: str) -> str:
    return f"{_RULES_CACHE_PREFIX}{company_id}"


async def get_company_rules(company_id: str) -> CompanyRuleSet:
    """Return ``company_id``'s current mandatory rule set, cache-first.

    Never raises and never returns ``None`` -- mirrors
    ``get_company_adapter`` exactly.
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
    """Replace ``company_id``'s mandatory rule set and invalidate the cache.

    Args:
        company_id: The tenant to write.
        rules: The full replacement rule list, each a plain dict with
            ``text`` (required), ``severity`` ("zorunlu"/"onerilen",
            default "zorunlu"), ``enabled`` (default True), and an optional
            ``id``. An item that already carries an id (an admin editing an
            existing rule) keeps it, so a judge verdict's own
            ``violated_rule_ids`` recorded before this edit still refers to
            something meaningful; a blank id gets a fresh server-assigned
            one (``K{n}``) so ids are never reused, even across edits that
            remove rules.

    Returns:
        The persisted rule set, with ``version`` bumped and ``updated_at``
        set to now.

    Raises:
        ValueError: If ``company_id`` doesn't exist.
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
        # Provider-internal bookkeeping, not part of CompanyRuleSet's own
        # shape -- from_dict reads only version/rules/updated_at, so this
        # extra key is silently ignored by every other reader.
        persisted["next_id_seq"] = next_seq
        merged_settings[_RULES_SETTINGS_KEY] = persisted
        company.settings = merged_settings

    cache = get_cache()
    await cache.delete(_rules_cache_key(company_id))
    return ruleset


#: Faz C3 Aşama 3 (#191) -- the Ollama model name a successful LoRA
#: training run publishes (`kachow-{slug}:v{n}`). Deliberately a *separate*
#: settings key from `_SETTINGS_KEY`, not folded into `CompanyAdapter`: a
#: model override is an infrastructure fact (which weights answer this
#: company's calls), not a style preference, and the two are set
#: independently -- a LoRA run does not have to succeed for a style-adapter
#: run (Aşama 2) to keep working, and vice versa.
#:
#: Written by `app.workers.training.run_lora_training_job` after a shadow
#: evaluation passes; **not consumed anywhere yet** -- wiring the live
#: draft/revise graphs to pick a company's model per request is a separate,
#: larger change (constructing/caching a graph per model instead of once
#: per process) intentionally left out of #191's scope. Read this value
#: once that wiring exists.
_MODEL_OVERRIDE_KEY = "llm_model_override"


async def get_llm_model_override(company_id: str) -> Optional[str]:
    """The Ollama model name a shadow-eval-passed LoRA adapter published
    for ``company_id``, or ``None`` if it has never trained one (the
    common case -- callers should fall back to ``settings.OLLAMA_MODEL``)."""
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
    """Record ``model_name`` as ``company_id``'s override, read-merge-write
    on ``CompanyModel.settings`` same as ``set_company_adapter``.

    Raises:
        ValueError: If ``company_id`` doesn't exist.
    """
    async with tenant_session(company_id, is_root=False) as session:
        result = await session.execute(select(CompanyModel).where(CompanyModel.id == company_id))
        company = result.scalar_one_or_none()
        if company is None:
            raise ValueError(f"Company '{company_id}' not found.")
        merged_settings = dict(company.settings or {})
        merged_settings[_MODEL_OVERRIDE_KEY] = model_name
        company.settings = merged_settings
