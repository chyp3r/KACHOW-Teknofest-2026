import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.companies.repository import CompanyRepository
from app.domains.companies.model.company_model import CompanyModel


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def repo(mock_session):
    return CompanyRepository(mock_session)


def _company(**overrides):
    fields = dict(
        id="company-1", name="Acme Holding", slug="acme", is_active=True, is_deleted=False, settings={}
    )
    fields.update(overrides)
    return CompanyModel(**fields)


@pytest.mark.asyncio
async def test_get_by_id(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = _company()
    mock_session.execute.return_value = mock_result

    company = await repo.get_by_id("company-1")
    assert company is not None
    assert company.id == "company-1"
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_by_slug(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = _company()
    mock_session.execute.return_value = mock_result

    company = await repo.get_by_slug("acme")
    assert company is not None
    assert company.slug == "acme"


@pytest.mark.asyncio
async def test_list_all(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [
        _company(id="1", slug="a"),
        _company(id="2", slug="b"),
    ]
    mock_session.execute.return_value = mock_result

    companies = await repo.list_all(offset=0, limit=20)
    assert len(companies) == 2
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_count_all(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 3
    mock_session.execute.return_value = mock_result

    total = await repo.count_all()
    assert total == 3


@pytest.mark.asyncio
async def test_create(repo, mock_session):
    company = _company()

    result = await repo.create(company)
    assert result is company
    mock_session.add.assert_called_once_with(company)
    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_update(repo, mock_session):
    company = _company()

    result = await repo.update(company, {"name": "Acme Corp"})
    assert result.name == "Acme Corp"
    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_soft_delete(repo, mock_session):
    company = _company()

    result = await repo.soft_delete(company)
    assert result.is_deleted is True
    assert result.is_active is False
    mock_session.flush.assert_called_once()
