"""Tests for the demo-company bootstrap.

SEED_DEMO_COMPANY is off globally in tests (see conftest.py's
`_disable_demo_company_seeding`), so every test here explicitly re-enables
it and stands in for `AsyncSessionLocal` with a mock session -- same
approach as test_unit_seeder.py.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.companies import seeder
from app.domains.companies.model.company_model import CompanyModel


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc_info):
        return False


def _result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def enabled_session(monkeypatch, mock_session):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SEED_DEMO_COMPANY", True)
    monkeypatch.setattr(
        seeder, "AsyncSessionLocal", lambda: _FakeSessionContext(mock_session)
    )
    return mock_session


@pytest.mark.asyncio
async def test_seed_demo_company_creates_it_when_missing(enabled_session):
    enabled_session.execute.return_value = _result(None)

    company_id = await seeder.seed_demo_company()

    assert company_id is not None
    enabled_session.add.assert_called_once()
    company = enabled_session.add.call_args.args[0]
    assert isinstance(company, CompanyModel)
    assert company.is_active is True
    enabled_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_seed_demo_company_returns_the_existing_id_without_creating(enabled_session):
    existing = CompanyModel(id="existing-id", name="Demo Kurum", slug="demo", is_active=True)
    enabled_session.execute.return_value = _result(existing)

    company_id = await seeder.seed_demo_company()

    assert company_id == "existing-id"
    enabled_session.add.assert_not_called()
    enabled_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_seed_demo_company_is_a_noop_when_disabled_and_none_exists(monkeypatch, mock_session):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SEED_DEMO_COMPANY", False)
    monkeypatch.setattr(
        seeder, "AsyncSessionLocal", lambda: _FakeSessionContext(mock_session)
    )
    mock_session.execute.return_value = _result(None)

    company_id = await seeder.seed_demo_company()

    assert company_id is None
    mock_session.add.assert_not_called()
