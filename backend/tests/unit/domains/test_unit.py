import pytest
from unittest.mock import AsyncMock, MagicMock

from app.domains.units.service import UnitService
from app.domains.units.schema.unit_schema import UnitCreate, UnitUpdate
from app.api.exceptions.conflict import ConflictException
from app.api.exceptions.not_found import NotFoundException


@pytest.mark.asyncio
async def test_create_unit_success():
    repository = MagicMock()
    repository.get_by_name = AsyncMock(return_value=None)
    repository.create = AsyncMock(side_effect=lambda unit: unit)

    service = UnitService(repository)
    schema = UnitCreate(name="Mali İşler", description="Bütçe ve ödemeler.")

    unit = await service.create_unit(schema)

    assert unit.name == "Mali İşler"
    assert unit.description == "Bütçe ve ödemeler."
    assert unit.is_active is True


@pytest.mark.asyncio
async def test_create_unit_rejects_duplicate_name():
    repository = MagicMock()
    repository.get_by_name = AsyncMock(return_value=MagicMock())

    service = UnitService(repository)
    schema = UnitCreate(name="Mali İşler", description="Bütçe ve ödemeler.")

    with pytest.raises(ConflictException):
        await service.create_unit(schema)


@pytest.mark.asyncio
async def test_get_unit_by_id_not_found():
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=None)

    service = UnitService(repository)

    with pytest.raises(NotFoundException):
        await service.get_unit_by_id("no-such-id")


@pytest.mark.asyncio
async def test_list_units():
    repository = MagicMock()
    repository.list_all = AsyncMock(return_value=[MagicMock(), MagicMock()])

    service = UnitService(repository)
    result = await service.list_units()

    assert len(result) == 2
    repository.list_all.assert_called_once()


@pytest.mark.asyncio
async def test_update_unit_success():
    repository = MagicMock()
    mock_unit = MagicMock()
    mock_unit.name = "Mali İşler"
    repository.get_by_id = AsyncMock(return_value=mock_unit)
    repository.update = AsyncMock(return_value=mock_unit)

    service = UnitService(repository)
    schema = UnitUpdate(description="Yeni açıklama", is_active=False)

    await service.update_unit("unit-1", schema)

    repository.update.assert_called_once()
    call_args = repository.update.call_args[0][1]
    assert call_args["description"] == "Yeni açıklama"
    assert call_args["is_active"] is False


@pytest.mark.asyncio
async def test_update_unit_rejects_renaming_to_an_existing_name():
    repository = MagicMock()
    mock_unit = MagicMock()
    mock_unit.name = "Mali İşler"
    repository.get_by_id = AsyncMock(return_value=mock_unit)
    repository.get_by_name = AsyncMock(return_value=MagicMock())

    service = UnitService(repository)
    schema = UnitUpdate(name="Destek Hizmetleri")

    with pytest.raises(ConflictException):
        await service.update_unit("unit-1", schema)


@pytest.mark.asyncio
async def test_update_unit_allows_keeping_the_same_name():
    repository = MagicMock()
    mock_unit = MagicMock()
    mock_unit.name = "Mali İşler"
    repository.get_by_id = AsyncMock(return_value=mock_unit)
    repository.update = AsyncMock(return_value=mock_unit)

    service = UnitService(repository)
    schema = UnitUpdate(name="Mali İşler", description="Güncellendi")

    await service.update_unit("unit-1", schema)

    repository.get_by_name.assert_not_called()
    repository.update.assert_called_once()


@pytest.mark.asyncio
async def test_delete_unit_success():
    repository = MagicMock()
    repository.delete = AsyncMock(return_value=True)

    service = UnitService(repository)
    await service.delete_unit("unit-1")
    repository.delete.assert_called_once_with("unit-1")


@pytest.mark.asyncio
async def test_delete_unit_not_found():
    repository = MagicMock()
    repository.delete = AsyncMock(return_value=False)

    service = UnitService(repository)
    with pytest.raises(NotFoundException):
        await service.delete_unit("unit-1")
