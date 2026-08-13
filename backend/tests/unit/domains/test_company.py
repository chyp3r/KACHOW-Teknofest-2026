import pytest
from unittest.mock import AsyncMock, MagicMock

from app.api.exceptions.conflict import ConflictException
from app.api.exceptions.not_found import NotFoundException
from app.api.exceptions.validation import ValidationException
from app.core.enums.user_role import UserRole
from app.domains.companies.model.company_model import CompanyModel
from app.domains.companies.schema.company_schema import CompanyCreate, CompanyUpdate
from app.domains.companies.service import CompanyService


def _company(**overrides):
    fields = dict(
        id="company-1",
        name="Acme Holding",
        slug="acme",
        tax_number=None,
        is_active=True,
        is_deleted=False,
        settings={},
        created_by="root-1",
    )
    fields.update(overrides)
    return CompanyModel(**fields)


@pytest.mark.asyncio
async def test_create_company_success():
    repository = MagicMock()
    repository.get_by_slug = AsyncMock(return_value=None)
    repository.create = AsyncMock(side_effect=lambda company: company)

    service = CompanyService(repository, MagicMock())
    schema = CompanyCreate(name="Acme Holding", slug="acme")

    company = await service.create_company(schema, created_by="root-1")

    assert company.name == "Acme Holding"
    assert company.slug == "acme"
    assert company.is_active is True
    assert company.is_deleted is False
    assert company.created_by == "root-1"


@pytest.mark.asyncio
async def test_create_company_rejects_duplicate_slug():
    repository = MagicMock()
    repository.get_by_slug = AsyncMock(return_value=_company())

    service = CompanyService(repository, MagicMock())
    schema = CompanyCreate(name="Acme Holding", slug="acme")

    with pytest.raises(ConflictException):
        await service.create_company(schema, created_by="root-1")


@pytest.mark.asyncio
async def test_get_company_by_id_not_found():
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=None)

    service = CompanyService(repository, MagicMock())

    with pytest.raises(NotFoundException):
        await service.get_company_by_id("no-such-id")


@pytest.mark.asyncio
async def test_get_company_by_id_treats_soft_deleted_as_not_found():
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=_company(is_deleted=True))

    service = CompanyService(repository, MagicMock())

    with pytest.raises(NotFoundException):
        await service.get_company_by_id("company-1")


@pytest.mark.asyncio
async def test_list_companies():
    repository = MagicMock()
    repository.list_all = AsyncMock(return_value=[_company(), _company(id="c2", slug="c2")])
    repository.count_all = AsyncMock(return_value=2)

    service = CompanyService(repository, MagicMock())
    companies, total = await service.list_companies(page=1, size=20)

    assert len(companies) == 2
    assert total == 2
    repository.list_all.assert_called_once_with(offset=0, limit=20)


@pytest.mark.asyncio
async def test_update_company_success():
    repository = MagicMock()
    company = _company()
    repository.get_by_id = AsyncMock(return_value=company)
    repository.update = AsyncMock(return_value=company)

    service = CompanyService(repository, MagicMock())
    schema = CompanyUpdate(name="Acme Corp", is_active=False)

    await service.update_company("company-1", schema)

    repository.update.assert_called_once()
    call_args = repository.update.call_args[0][1]
    assert call_args["name"] == "Acme Corp"
    assert call_args["is_active"] is False


@pytest.mark.asyncio
async def test_delete_company_soft_deletes():
    repository = MagicMock()
    company = _company()
    repository.get_by_id = AsyncMock(return_value=company)
    repository.soft_delete = AsyncMock(side_effect=lambda c: c)

    service = CompanyService(repository, MagicMock())
    await service.delete_company("company-1")

    repository.soft_delete.assert_called_once_with(company)


@pytest.mark.asyncio
async def test_delete_company_not_found():
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=None)

    service = CompanyService(repository, MagicMock())
    with pytest.raises(NotFoundException):
        await service.delete_company("no-such-id")


# ==========================================
# assign_admin
# ==========================================
@pytest.mark.asyncio
async def test_assign_admin_promotes_a_user_of_the_same_company():
    repository = MagicMock()
    company = _company()
    repository.get_by_id = AsyncMock(return_value=company)

    user_repository = MagicMock()
    member = MagicMock(id="user-1", company_id="company-1", role=UserRole.EMPLOYEE.value)
    user_repository.get_by_id = AsyncMock(return_value=member)
    user_repository.update = AsyncMock(side_effect=lambda u, data: u)

    service = CompanyService(repository, user_repository)
    await service.assign_admin("company-1", "user-1")

    user_repository.update.assert_called_once_with(member, {"role": UserRole.ADMIN.value})


@pytest.mark.asyncio
async def test_assign_admin_rejects_a_user_from_a_different_company():
    """The self-escalation-adjacent cross-tenant hole this method exists to
    close: a root operator (or a bug) must not be able to silently move a
    stranger from another company into this one by promoting them."""
    repository = MagicMock()
    company = _company()
    repository.get_by_id = AsyncMock(return_value=company)

    user_repository = MagicMock()
    stranger = MagicMock(id="user-9", company_id="company-9", role=UserRole.EMPLOYEE.value)
    user_repository.get_by_id = AsyncMock(return_value=stranger)

    service = CompanyService(repository, user_repository)
    with pytest.raises(ValidationException):
        await service.assign_admin("company-1", "user-9")

    user_repository.update.assert_not_called()


@pytest.mark.asyncio
async def test_assign_admin_user_not_found():
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=_company())

    user_repository = MagicMock()
    user_repository.get_by_id = AsyncMock(return_value=None)

    service = CompanyService(repository, user_repository)
    with pytest.raises(NotFoundException):
        await service.assign_admin("company-1", "no-such-user")
