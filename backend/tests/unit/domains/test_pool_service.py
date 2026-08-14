from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.domains.documents.model.document_model import DocumentModel
from app.domains.pools.model.document_pool_model import DocumentPoolModel
from app.domains.pools.schema.pool_schema import PoolPushRequest
from app.domains.pools.service import PoolService
from app.domains.users.model.user_model import UserModel


def _user(**overrides) -> UserModel:
    fields = dict(
        id="user-1", company_id="company-1", username="u1", email="u1@example.com",
        role="employee", clearance_level="hizmete_ozel", is_active=True, is_deleted=False,
        hashed_password="x", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return UserModel(**fields)


def _document(**overrides) -> DocumentModel:
    fields = dict(
        id="doc-1", company_id="company-1", owner_id="admin-1", file_name="a.pdf",
        sensitivity_level="unmarked",
    )
    fields.update(overrides)
    return DocumentModel(**fields)


def _pool(**overrides) -> DocumentPoolModel:
    fields = dict(
        id="pool-1", company_id="company-1", owner_type="user", owner_id="user-1",
        name="Kişisel Havuz", is_default=True,
    )
    fields.update(overrides)
    return DocumentPoolModel(**fields)


@pytest.fixture
def pool_repo():
    return AsyncMock()


@pytest.fixture
def item_repo():
    return AsyncMock()


@pytest.fixture
def document_repo():
    return AsyncMock()


@pytest.fixture
def user_repo():
    return AsyncMock()


@pytest.fixture
def membership_repo():
    return AsyncMock()


@pytest.fixture
def service(pool_repo, item_repo, document_repo, user_repo, membership_repo):
    return PoolService(pool_repo, item_repo, document_repo, user_repo, membership_repo)


async def test_get_or_create_personal_pool_delegates_to_repository(service, pool_repo):
    pool_repo.get_or_create_default.return_value = _pool()

    pool = await service.get_or_create_personal_pool("user-1", "company-1")

    assert pool.owner_id == "user-1"
    pool_repo.get_or_create_default.assert_awaited_once_with(
        "user", "user-1", "company-1", name="Kişisel Havuz"
    )


async def test_list_pool_items_404s_when_pool_missing(service, pool_repo):
    pool_repo.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await service.list_pool_items("pool-1", "company-1", _user())


async def test_list_pool_items_denies_a_non_owner_employee(service, pool_repo):
    pool_repo.get_by_id.return_value = _pool(owner_id="someone-else")

    with pytest.raises(AuthorizationException):
        await service.list_pool_items("pool-1", "company-1", _user(id="user-1"))


async def test_list_pool_items_allows_an_admin_regardless_of_ownership(service, pool_repo, item_repo):
    pool_repo.get_by_id.return_value = _pool(owner_id="someone-else")
    item_repo.list_for_pool.return_value = []
    item_repo.count_for_pool.return_value = 0

    items, total = await service.list_pool_items("pool-1", "company-1", _user(role="admin"))

    assert items == []
    assert total == 0


async def test_push_404s_when_document_missing(service, document_repo):
    document_repo.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await service.push(
            PoolPushRequest(document_id="doc-1", recipient_ids=["user-1"]), _user(role="admin"), "company-1"
        )


async def test_push_reports_not_found_for_a_missing_recipient(service, document_repo, user_repo):
    document_repo.get_by_id.return_value = _document()
    user_repo.get_by_id_in_company.return_value = None

    results = await service.push(
        PoolPushRequest(document_id="doc-1", recipient_ids=["ghost"]), _user(role="admin"), "company-1"
    )

    assert results[0].status == "not_found"


async def test_push_denies_a_recipient_below_clearance(service, document_repo, user_repo, pool_repo, item_repo):
    document_repo.get_by_id.return_value = _document(sensitivity_level="gizli")
    user_repo.get_by_id_in_company.return_value = _user(clearance_level="hizmete_ozel")

    results = await service.push(
        PoolPushRequest(document_id="doc-1", recipient_ids=["user-1"]), _user(role="admin"), "company-1"
    )

    assert results[0].status == "denied_clearance"
    pool_repo.get_or_create_default.assert_not_awaited()
    item_repo.create.assert_not_awaited()


async def test_push_succeeds_for_a_cleared_recipient(service, document_repo, user_repo, pool_repo, item_repo):
    document_repo.get_by_id.return_value = _document(sensitivity_level="unmarked")
    user_repo.get_by_id_in_company.return_value = _user(clearance_level="hizmete_ozel")
    pool_repo.get_or_create_default.return_value = _pool()
    item_repo.exists.return_value = False

    results = await service.push(
        PoolPushRequest(document_id="doc-1", recipient_ids=["user-1"], note="bkz"), _user(role="admin"), "company-1"
    )

    assert results[0].status == "pushed"
    item_repo.create.assert_awaited_once()
    created = item_repo.create.call_args.args[0]
    assert created.source == "manager_push"
    assert created.note == "bkz"


async def test_push_skips_duplicate_without_erroring(service, document_repo, user_repo, pool_repo, item_repo):
    document_repo.get_by_id.return_value = _document()
    user_repo.get_by_id_in_company.return_value = _user()
    pool_repo.get_or_create_default.return_value = _pool()
    item_repo.exists.return_value = True

    results = await service.push(
        PoolPushRequest(document_id="doc-1", recipient_ids=["user-1"]), _user(role="admin"), "company-1"
    )

    assert results[0].status == "pushed"
    item_repo.create.assert_not_awaited()


async def test_push_resolves_recipients_from_a_unit(service, document_repo, user_repo, membership_repo, pool_repo, item_repo):
    document_repo.get_by_id.return_value = _document()
    membership_repo.list_for_unit.return_value = [(None, _user(id="user-1")), (None, _user(id="user-2"))]
    user_repo.get_by_id_in_company.side_effect = [_user(id="user-1"), _user(id="user-2")]
    pool_repo.get_or_create_default.return_value = _pool()
    item_repo.exists.return_value = False

    results = await service.push(
        PoolPushRequest(document_id="doc-1", unit_id="unit-1"), _user(role="admin"), "company-1"
    )

    assert {r.user_id for r in results} == {"user-1", "user-2"}


async def test_remove_item_404s_when_item_belongs_to_a_different_pool(service, pool_repo, item_repo):
    pool_repo.get_by_id.return_value = _pool(owner_id="user-1")
    item_repo.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await service.remove_item("pool-1", "item-1", "company-1", _user(id="user-1"))


async def test_acknowledge_item_denies_a_non_owner(service, pool_repo, item_repo):
    from app.domains.pools.model.document_pool_item_model import DocumentPoolItemModel

    item_repo.get_by_id.return_value = DocumentPoolItemModel(
        id="item-1", company_id="company-1", pool_id="pool-1", document_id="doc-1", added_by="admin-1"
    )
    pool_repo.get_by_id.return_value = _pool(owner_id="someone-else")

    with pytest.raises(AuthorizationException):
        await service.acknowledge_item("item-1", "company-1", _user(id="user-1"))
