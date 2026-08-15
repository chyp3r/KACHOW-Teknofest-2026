"""Tests for the runtime adapter's read/write layer (Faz C2, #185).

Same isolation strategy as test_run_recorder.py: tenant_session is stood
in for with a mock session rather than hitting a real database, and
get_cache() is stood in for with a fake in-memory Redis so these test the
provider's own cache-then-DB logic, not Postgres/Redis themselves.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.adapters.company_adapter import CompanyAdapter
from app.domains.companies import provider as provider_module
from app.domains.companies.model.company_model import CompanyModel


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc_info):
        return False


class _FakeCache:
    """A minimal in-memory stand-in for RedisCache's async interface."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, expire_seconds=None):
        self.store[key] = value
        return True

    async def delete(self, key):
        existed = key in self.store
        self.store.pop(key, None)
        return existed


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def fake_cache():
    return _FakeCache()


@pytest.fixture(autouse=True)
def _patch_infra(monkeypatch, mock_session, fake_cache):
    monkeypatch.setattr(
        provider_module,
        "tenant_session",
        lambda company_id=None, is_root=False: _FakeSessionContext(mock_session),
    )
    monkeypatch.setattr(provider_module, "get_cache", lambda: fake_cache)


def _company(**overrides) -> CompanyModel:
    fields = dict(id="company-1", name="Test A.Ş.", slug="test", is_active=True, settings={})
    fields.update(overrides)
    return CompanyModel(**fields)


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ==========================================
# get_company_adapter
# ==========================================
async def test_get_adapter_for_a_falsy_company_id_never_touches_cache_or_db(mock_session):
    adapter = await provider_module.get_company_adapter("")

    assert adapter == CompanyAdapter.empty("")
    mock_session.execute.assert_not_awaited()


async def test_get_adapter_reads_from_db_on_a_cold_cache(mock_session, fake_cache):
    company = _company(
        settings={"company_adapter": {"version": 2, "style_rules": ["Kısa yaz."]}}
    )
    mock_session.execute.return_value = _scalar_result(company.settings)

    adapter = await provider_module.get_company_adapter("company-1")

    assert adapter.version == 2
    assert adapter.style_rules == ("Kısa yaz.",)
    # The cold-cache read populates the cache for next time.
    assert "company_adapter:company-1" in fake_cache.store


async def test_get_adapter_serves_a_warm_cache_without_touching_the_db(mock_session, fake_cache):
    cached = CompanyAdapter(company_id="company-1", version=5, style_rules=("Kural.",))
    fake_cache.store["company_adapter:company-1"] = json.dumps(cached.to_dict())

    adapter = await provider_module.get_company_adapter("company-1")

    assert adapter.version == 5
    mock_session.execute.assert_not_awaited()


async def test_get_adapter_for_a_company_with_nothing_configured_resolves_to_empty(
    mock_session,
):
    company = _company(settings={})
    mock_session.execute.return_value = _scalar_result(company.settings)

    adapter = await provider_module.get_company_adapter("company-1")

    assert adapter.is_empty


async def test_get_adapter_fails_open_to_empty_when_the_db_read_raises(mock_session):
    mock_session.execute.side_effect = RuntimeError("connection lost")

    adapter = await provider_module.get_company_adapter("company-1")

    assert adapter == CompanyAdapter.empty("company-1")


async def test_get_adapter_recovers_from_a_malformed_cache_value_by_re_reading(
    mock_session, fake_cache
):
    fake_cache.store["company_adapter:company-1"] = "{not valid json"
    company = _company(settings={"company_adapter": {"version": 1}})
    mock_session.execute.return_value = _scalar_result(company.settings)

    adapter = await provider_module.get_company_adapter("company-1")

    assert adapter.version == 1


# ==========================================
# set_company_adapter
# ==========================================
async def test_set_adapter_bumps_the_version_and_stamps_trained_at(mock_session, fake_cache):
    company = _company(settings={"company_adapter": {"version": 3}})
    mock_session.execute.return_value = _scalar_result(company)

    adapter = await provider_module.set_company_adapter(
        "company-1", style_rules=["Yeni kural."], sample_count=12
    )

    assert adapter.version == 4
    assert adapter.style_rules == ("Yeni kural.",)
    assert adapter.trained_at is not None
    assert adapter.sample_count == 12


async def test_set_adapter_merges_into_settings_without_clobbering_other_keys(mock_session):
    company = _company(settings={"other_flag": True})
    mock_session.execute.return_value = _scalar_result(company)

    await provider_module.set_company_adapter("company-1", style_rules=["Kural."])

    assert company.settings["other_flag"] is True
    assert "company_adapter" in company.settings


async def test_set_adapter_invalidates_the_cache(mock_session, fake_cache):
    company = _company()
    mock_session.execute.return_value = _scalar_result(company)
    fake_cache.store["company_adapter:company-1"] = json.dumps(
        CompanyAdapter(company_id="company-1", version=1).to_dict()
    )

    await provider_module.set_company_adapter("company-1", style_rules=["Kural."])

    assert "company_adapter:company-1" not in fake_cache.store


async def test_set_adapter_raises_for_an_unknown_company(mock_session):
    mock_session.execute.return_value = _scalar_result(None)

    with pytest.raises(ValueError):
        await provider_module.set_company_adapter("missing-co", style_rules=["Kural."])


# ==========================================
# llm_model_override (Faz C3 Aşama 3, #191)
# ==========================================
async def test_get_model_override_for_a_falsy_company_id_never_touches_the_db(mock_session):
    result = await provider_module.get_llm_model_override("")

    assert result is None
    mock_session.execute.assert_not_awaited()


async def test_get_model_override_returns_none_when_nothing_was_ever_trained(mock_session):
    company = _company(settings={})
    mock_session.execute.return_value = _scalar_result(company.settings)

    result = await provider_module.get_llm_model_override("company-1")

    assert result is None


async def test_get_model_override_reads_the_published_model_name(mock_session):
    company = _company(settings={"llm_model_override": "kachow-acme:v1"})
    mock_session.execute.return_value = _scalar_result(company.settings)

    result = await provider_module.get_llm_model_override("company-1")

    assert result == "kachow-acme:v1"


async def test_get_model_override_fails_open_to_none_when_the_db_read_raises(mock_session):
    mock_session.execute.side_effect = RuntimeError("connection lost")

    result = await provider_module.get_llm_model_override("company-1")

    assert result is None


async def test_set_model_override_writes_without_touching_other_settings_keys(mock_session):
    company = _company(settings={"company_adapter": {"version": 1}})
    mock_session.execute.return_value = _scalar_result(company)

    await provider_module.set_llm_model_override("company-1", "kachow-acme:v1")

    assert company.settings["llm_model_override"] == "kachow-acme:v1"
    assert "company_adapter" in company.settings


async def test_set_model_override_raises_for_an_unknown_company(mock_session):
    mock_session.execute.return_value = _scalar_result(None)

    with pytest.raises(ValueError):
        await provider_module.set_llm_model_override("missing-co", "kachow-acme:v1")
