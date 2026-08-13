import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.units.repository import UnitRepository
from app.domains.units.model.unit_model import UnitModel


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def repo(mock_session):
    return UnitRepository(mock_session)


def _unit(**overrides):
    fields = dict(
        id="unit-1",
        company_id="company-1",
        name="Mali İşler",
        description="Bütçe ve ödemeler.",
        is_active=True,
    )
    fields.update(overrides)
    return UnitModel(**fields)


@pytest.mark.asyncio
async def test_get_by_id(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = _unit()
    mock_session.execute.return_value = mock_result

    unit = await repo.get_by_id("unit-1", "company-1")
    assert unit is not None
    assert unit.id == "unit-1"
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_by_name(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = _unit()
    mock_session.execute.return_value = mock_result

    unit = await repo.get_by_name("Mali İşler", "company-1")
    assert unit is not None
    assert unit.name == "Mali İşler"
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_list_all(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [
        _unit(id="1", name="A"),
        _unit(id="2", name="B", is_active=False),
    ]
    mock_session.execute.return_value = mock_result

    units = await repo.list_all("company-1")
    assert len(units) == 2
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_list_active(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [_unit(id="1", name="A")]
    mock_session.execute.return_value = mock_result

    units = await repo.list_active("company-1")
    assert len(units) == 1
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_create(repo, mock_session):
    new_unit = _unit()

    result = await repo.create(new_unit)
    assert result == new_unit
    mock_session.add.assert_called_once_with(new_unit)
    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_update(repo, mock_session):
    unit = _unit()

    result = await repo.update(unit, {"description": "Yeni açıklama"})
    assert result.description == "Yeni açıklama"
    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_update_can_set_is_active_to_false(repo, mock_session):
    unit = _unit(is_active=True)

    result = await repo.update(unit, {"is_active": False})
    assert result.is_active is False
    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_delete_existing(repo, mock_session):
    mock_result = MagicMock()
    mock_result.rowcount = 1
    mock_session.execute.return_value = mock_result

    result = await repo.delete("unit-1", "company-1")
    assert result is True
    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_delete_missing(repo, mock_session):
    mock_result = MagicMock()
    mock_result.rowcount = 0
    mock_session.execute.return_value = mock_result

    result = await repo.delete("no-such-id", "company-1")
    assert result is False
