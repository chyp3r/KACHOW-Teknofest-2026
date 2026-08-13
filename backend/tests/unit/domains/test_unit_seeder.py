"""Tests for the default routable-unit bootstrap.

SEED_DEFAULT_UNITS is off globally in tests (see conftest.py's
`_disable_default_unit_seeding`), so every test here explicitly re-enables
it and stands in for `tenant_session` with a mock session rather than
hitting a real database -- same approach as test_user_seeder.py.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.units import seeder
from app.domains.units.model.unit_model import UnitModel


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
    """Turn seeding on and point AsyncSessionLocal at a mock session."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "SEED_DEFAULT_UNITS", True)
    monkeypatch.setattr(
        seeder,
        "tenant_session",
        lambda company_id, is_root=False: _FakeSessionContext(mock_session),
    )
    return mock_session


_UNIT = seeder._SeedUnit(name="Mali İşler", description="Bütçe ve ödemeler.")


# ==========================================
# _seed_one
# ==========================================
@pytest.mark.asyncio
async def test_seed_one_creates_the_unit_when_missing(enabled_session):
    enabled_session.execute.return_value = _result(None)

    created = await seeder._seed_one(_UNIT, "company-1")

    assert created is True
    enabled_session.add.assert_called_once()
    unit = enabled_session.add.call_args.args[0]
    assert isinstance(unit, UnitModel)
    assert unit.name == "Mali İşler"
    assert unit.description == "Bütçe ve ödemeler."
    assert unit.is_active is True
    enabled_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_seed_one_skips_when_name_already_exists(enabled_session):
    existing = UnitModel(id="u1", name="Mali İşler", description="Var olan.", is_active=True)
    enabled_session.execute.return_value = _result(existing)

    created = await seeder._seed_one(_UNIT, "company-1")

    assert created is False
    enabled_session.add.assert_not_called()
    enabled_session.commit.assert_not_called()


# ==========================================
# seed_default_units
# ==========================================
@pytest.mark.asyncio
async def test_seed_default_units_is_a_noop_when_disabled(monkeypatch, mock_session):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SEED_DEFAULT_UNITS", False)
    monkeypatch.setattr(
        seeder,
        "tenant_session",
        lambda company_id, is_root=False: _FakeSessionContext(mock_session),
    )

    await seeder.seed_default_units("company-1")

    mock_session.execute.assert_not_called()
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_seed_default_units_creates_every_default_unit(enabled_session):
    enabled_session.execute.return_value = _result(None)

    await seeder.seed_default_units("company-1")

    expected_names = {u.name for u in seeder._seed_units()}
    assert enabled_session.add.call_count == len(expected_names)
    seeded_names = {call.args[0].name for call in enabled_session.add.call_args_list}
    assert seeded_names == expected_names
    assert enabled_session.commit.await_count == len(expected_names)


@pytest.mark.asyncio
async def test_seed_default_units_tolerates_one_unit_failing(monkeypatch, enabled_session):
    """One unit's DB error must not stop the others from being seeded."""
    calls = []

    async def fake_seed_one(unit, company_id):
        calls.append(unit.name)
        if unit.name == "Hukuk Müşavirliği":
            raise Exception("db exploded")
        return True

    monkeypatch.setattr(seeder, "_seed_one", fake_seed_one)

    await seeder.seed_default_units("company-1")

    expected_names = [u.name for u in seeder._seed_units()]
    assert calls == expected_names
