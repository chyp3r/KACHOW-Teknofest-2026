"""Real-Postgres coverage for `AuditLogRepository.append`/`AuditService.
verify_chain`.

`tests/unit/domains/test_audit_service.py` covers the hash-chain *logic*
against hand-built `AuditLogModel` instances and a mocked repository -- it
never exercises `AuditLogRepository.append`'s own SQL, which is exactly
where a real bug shipped once already (a `NameError` from an incomplete
rename during this same phase's development: `_hashable_fields` renamed to
`hashable_fields` at its definition but not at its one internal call site,
invisible to the mocked unit tests since they never call the real
`append()` at all). This file exists specifically to keep that class of bug
caught by an automated test, not just by manual live smoke-testing.
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# AuditLogModel's FKs reference "companies"/"users" by table name, resolved
# against SQLAlchemy's shared Base.metadata at flush time -- these imports
# are load-bearing (not unused) even though nothing below references the
# classes by name: without them in this test process's import graph, the
# ORM flush below raises NoReferencedTableError since those tables were
# never registered. tests/integration/conftest.py's own fixtures sidestep
# this entirely by using raw SQL instead of ORM models; this file uses the
# real AuditLogRepository.append() on purpose (see the module docstring),
# so it needs the real model graph instead.
from app.domains.companies.model.company_model import CompanyModel  # noqa: F401
from app.domains.users.model.user_model import UserModel  # noqa: F401
from app.domains.audit.repository import GENESIS_HASH, AuditLogRepository
from app.domains.audit.service import AuditService

pytestmark = pytest.mark.integration


async def test_append_writes_a_real_row_and_computes_the_chain_link(owner_engine, two_companies):
    """The regression case: append() must not raise, and must produce a
    genesis-linked, non-empty hash -- exercising the exact code path the
    NameError above broke."""
    company_id = two_companies["a"]["company_id"]
    session_maker = async_sessionmaker(bind=owner_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        repo = AuditLogRepository(session)
        entry = await repo.append(
            company_id=company_id,
            actor_user_id=two_companies["a"]["user_id"],
            actor_role="admin",
            action="unit:create",
            resource_type="unit",
            resource_id=uuid4().hex,
            after={"name": "Test Unit"},
        )
        await session.commit()

    assert entry.seq == 1
    assert entry.prev_hash == GENESIS_HASH
    assert entry.hash and entry.hash != GENESIS_HASH


async def test_append_chains_sequential_entries_within_one_company(owner_engine, two_companies):
    company_id = two_companies["a"]["company_id"]
    session_maker = async_sessionmaker(bind=owner_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        repo = AuditLogRepository(session)
        first = await repo.append(
            company_id=company_id, actor_user_id=None, actor_role=None, action="unit:create"
        )
        second = await repo.append(
            company_id=company_id, actor_user_id=None, actor_role=None, action="unit:update"
        )
        await session.commit()

    assert first.seq == 1
    assert second.seq == 2
    assert second.prev_hash == first.hash


async def test_append_keeps_separate_companies_on_separate_chains(owner_engine, two_companies):
    """Company B's first entry must start its own chain at seq=1 with the
    genesis prev_hash, unaffected by however many rows company A already has."""
    session_maker = async_sessionmaker(bind=owner_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        repo = AuditLogRepository(session)
        await repo.append(
            company_id=two_companies["a"]["company_id"],
            actor_user_id=None,
            actor_role=None,
            action="unit:create",
        )
        await repo.append(
            company_id=two_companies["a"]["company_id"],
            actor_user_id=None,
            actor_role=None,
            action="unit:update",
        )
        company_b_first = await repo.append(
            company_id=two_companies["b"]["company_id"],
            actor_user_id=None,
            actor_role=None,
            action="unit:create",
        )
        await session.commit()

    assert company_b_first.seq == 1
    assert company_b_first.prev_hash == GENESIS_HASH


async def test_append_supports_the_system_wide_null_company_chain(owner_engine, two_companies):
    """`company_id=None` (a ROOT system-wide action) gets its own chain,
    using `IS NOT DISTINCT FROM` under the hood (see
    `AuditLogRepository._next_seq_and_prev_hash`'s docstring) -- not the
    same class of NULL-grouping bug `DraftRepository.list_drafts` had."""
    session_maker = async_sessionmaker(bind=owner_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        repo = AuditLogRepository(session)
        # A company-scoped row first, to prove it doesn't leak into the
        # NULL chain's own sequence numbering.
        await repo.append(
            company_id=two_companies["a"]["company_id"],
            actor_user_id=None,
            actor_role=None,
            action="unit:create",
        )
        system_first = await repo.append(
            company_id=None, actor_user_id=None, actor_role="root", action="company:create"
        )
        system_second = await repo.append(
            company_id=None, actor_user_id=None, actor_role="root", action="company:create"
        )
        await session.commit()

    assert system_first.seq == 1
    assert system_first.prev_hash == GENESIS_HASH
    assert system_second.seq == 2
    assert system_second.prev_hash == system_first.hash


async def test_verify_chain_confirms_a_real_persisted_chain_is_valid(owner_engine, two_companies):
    """End-to-end: append real rows, then verify them back through
    `AuditService.verify_chain` (not a hand-built fixture, unlike the unit
    tests) -- confirms `append`'s writes and `verify_chain`'s reads agree on
    the same hash formula."""
    company_id = two_companies["a"]["company_id"]
    session_maker = async_sessionmaker(bind=owner_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        repo = AuditLogRepository(session)
        for action in ("unit:create", "unit:update", "unit:delete"):
            await repo.append(
                company_id=company_id, actor_user_id=None, actor_role="admin", action=action
            )
        await session.commit()

        result = await AuditService(repo).verify_chain(company_id)

    assert result.valid is True
    assert result.rows_checked == 3
