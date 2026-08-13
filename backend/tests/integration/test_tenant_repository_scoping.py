"""Proof that the repository layer's own `company_id` filter is sufficient on its own.

Deliberately uses `owner_engine` -- the connection RLS does nothing for --
for every query here. The point is the inverse of `test_rls_isolation.py`:
row-level security is this project's *second* line of defense (see migration
``0013_rls``'s own module docstring, and the tenancy plan's §3.4), and the
primary one -- every repository method taking and filtering on an explicit
`company_id` -- has to hold up completely on its own, with RLS switched off
entirely, or "RLS is the second line of defense" would be wishful thinking
rather than something actually true of this codebase.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domains.documents.repository import DocumentRepository
from app.domains.units.repository import UnitRepository
from app.domains.users.repository import UserRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def owner_session_maker(owner_engine):
    return async_sessionmaker(bind=owner_engine, class_=AsyncSession, expire_on_commit=False)


async def test_document_repository_get_by_id_ignores_a_wrong_company_id(owner_session_maker, two_companies):
    async with owner_session_maker() as session:
        repo = DocumentRepository(session)
        # Company A's own storage_path, looked up under company B's scope.
        document = await repo.get_by_id(
            two_companies["a"]["document_id"], two_companies["b"]["company_id"]
        )

    assert document is None


async def test_document_repository_get_by_id_finds_it_under_its_own_company(owner_session_maker, two_companies):
    async with owner_session_maker() as session:
        repo = DocumentRepository(session)
        document = await repo.get_by_id(
            two_companies["a"]["document_id"], two_companies["a"]["company_id"]
        )

    assert document is not None
    assert document.id == two_companies["a"]["document_id"]


async def test_document_repository_list_for_owner_never_crosses_companies(owner_session_maker, two_companies):
    async with owner_session_maker() as session:
        repo = DocumentRepository(session)
        company_a_docs = await repo.list_for_owner(
            two_companies["a"]["company_id"], owner_id=None, skip=0, limit=100
        )

    ids = {d.id for d in company_a_docs}
    assert two_companies["a"]["document_id"] in ids
    assert two_companies["b"]["document_id"] not in ids


async def test_unit_repository_never_returns_a_different_companys_unit(owner_session_maker, two_companies):
    async with owner_session_maker() as session:
        # Raw SQL, not the ORM model: constructing a UnitModel here would
        # make SQLAlchemy resolve its `company_id` foreign key against
        # `Base.metadata`, which only has `companies` mapped if something
        # in this test module's import graph touched CompanyModel -- easy
        # to get right by accident and easy to break by moving an import.
        # `two_companies`'s own setup fixture uses the same raw-SQL style
        # for exactly this reason.
        await session.execute(
            text(
                "INSERT INTO units (id, company_id, name, description, is_active, created_at, updated_at) "
                "VALUES ('repo-scoping-test-unit', :cid, 'Repo Scoping Test Unit', 'desc', true, now(), now())"
            ),
            {"cid": two_companies["a"]["company_id"]},
        )
        await session.commit()

        repo = UnitRepository(session)
        # Created under company A, looked up under company B.
        found = await repo.get_by_id("repo-scoping-test-unit", two_companies["b"]["company_id"])
        found_under_own_company = await repo.get_by_id(
            "repo-scoping-test-unit", two_companies["a"]["company_id"]
        )

    assert found is None
    assert found_under_own_company is not None


async def test_user_repository_get_by_id_in_company_ignores_a_wrong_company_id(
    owner_session_maker, two_companies
):
    async with owner_session_maker() as session:
        repo = UserRepository(session)
        user = await repo.get_by_id_in_company(
            two_companies["a"]["user_id"], two_companies["b"]["company_id"]
        )

    assert user is None


async def test_manager_of_company_a_repository_call_cannot_reach_company_bs_document(
    owner_session_maker, two_companies
):
    """Regression guard matching the tenancy plan's own §10 scenario: a manager
    role's elevated (`bypasses_ownership`) access is still bounded by the
    mandatory `company_id` filter one layer below it -- this asserts that
    boundary at the repository level directly, independent of the router/authz
    layers already covered by tests/unit/api/test_ownership.py."""
    async with owner_session_maker() as session:
        repo = DocumentRepository(session)
        # bypasses_ownership()==True means owner_id is ignored -- but company_id
        # never is, regardless of role.
        result = await repo.get_by_id(
            two_companies["b"]["document_id"], two_companies["a"]["company_id"]
        )

    assert result is None
