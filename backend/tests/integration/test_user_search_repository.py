"""`UserRepository.search`/`count_search` against a real, migrated Postgres.

Unlike the mocked service-level tests, the ILIKE substring match, the
per-user primary-unit subquery, and the `unit_id` `EXISTS` filter are real
SQL this file is the only place that actually exercises.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domains.users.repository import UserRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def owner_session_maker(owner_engine):
    return async_sessionmaker(bind=owner_engine, class_=AsyncSession, expire_on_commit=False)


async def test_search_q_matches_only_within_its_own_company(owner_session_maker, two_companies):
    company_a = two_companies["a"]
    async with owner_session_maker() as session:
        repo = UserRepository(session)
        # `two_companies` names each user "rls-test-<label>-<hex>".
        results = await repo.search(company_a["company_id"], q="rls-test-a")

    ids = {user.id for user, _unit_name in results}
    assert company_a["user_id"] in ids


async def test_search_q_never_crosses_companies(owner_session_maker, two_companies):
    company_a, company_b = two_companies["a"], two_companies["b"]
    async with owner_session_maker() as session:
        repo = UserRepository(session)
        results = await repo.search(company_a["company_id"], q="rls-test")

    ids = {user.id for user, _unit_name in results}
    assert company_a["user_id"] in ids
    assert company_b["user_id"] not in ids


async def test_search_unit_id_filter_matches_a_member(owner_session_maker, two_companies):
    company_a = two_companies["a"]
    async with owner_session_maker() as session:
        repo = UserRepository(session)
        results = await repo.search(company_a["company_id"], unit_id=company_a["unit_id"])

    ids = {user.id for user, _unit_name in results}
    assert company_a["user_id"] in ids


async def test_search_unit_id_filter_excludes_a_different_companys_unit(owner_session_maker, two_companies):
    company_a, company_b = two_companies["a"], two_companies["b"]
    async with owner_session_maker() as session:
        repo = UserRepository(session)
        # company B's unit_id, scoped under company A -- must match nothing,
        # not silently fall back to an unfiltered listing.
        results = await repo.search(company_a["company_id"], unit_id=company_b["unit_id"])

    assert results == []


async def test_search_role_filter(owner_session_maker, two_companies):
    company_a = two_companies["a"]
    async with owner_session_maker() as session:
        repo = UserRepository(session)
        employees = await repo.search(company_a["company_id"], role="employee")
        admins = await repo.search(company_a["company_id"], role="admin")

    assert company_a["user_id"] in {user.id for user, _ in employees}
    assert company_a["user_id"] not in {user.id for user, _ in admins}


async def test_count_search_matches_search_length(owner_session_maker, two_companies):
    company_a = two_companies["a"]
    async with owner_session_maker() as session:
        repo = UserRepository(session)
        results = await repo.search(company_a["company_id"], q="rls-test-a")
        total = await repo.count_search(company_a["company_id"], q="rls-test-a")

    assert total == len(results)
