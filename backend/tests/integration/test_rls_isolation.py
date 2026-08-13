"""Cross-company isolation, enforced by Postgres itself via the `kachow_app` role.

Every query here goes through `app_engine` (the restricted role) with GUCs
set directly via `app_session` -- no repository, no FastAPI, no mocks. The
question this file answers is narrow and deliberate: does the *database*
refuse to cross a tenant boundary, independent of whether the application
code above it remembers to filter correctly. `test_tenant_repository_
scoping.py` is the complementary check for the other direction (does the
repository layer already suffice on its own, RLS or not).
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import app_session

pytestmark = pytest.mark.integration


async def test_no_guc_set_sees_zero_rows_on_every_rls_table(app_engine, two_companies):
    """A session that never set app.current_company_id (a forgotten GUC, a stray
    raw-SQL connection) must see nothing -- the fail-secure default, not an error."""
    session = await app_session(app_engine, company_id=None, is_root=False)
    try:
        for table in ("users", "units", "documents", "invited_emails"):
            count = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert count == 0, f"{table}: expected 0 rows with no tenant GUC set, got {count}"
    finally:
        await session.close()


async def test_company_a_sees_only_its_own_document(app_engine, two_companies):
    session = await app_session(app_engine, company_id=two_companies["a"]["company_id"])
    try:
        rows = (await session.execute(text("SELECT id FROM documents"))).scalars().all()
    finally:
        await session.close()

    assert rows == [two_companies["a"]["document_id"]]


async def test_company_b_sees_only_its_own_document(app_engine, two_companies):
    session = await app_session(app_engine, company_id=two_companies["b"]["company_id"])
    try:
        rows = (await session.execute(text("SELECT id FROM documents"))).scalars().all()
    finally:
        await session.close()

    assert rows == [two_companies["b"]["document_id"]]


async def test_company_a_cannot_select_company_bs_document_by_id(app_engine, two_companies):
    """Even a direct, targeted lookup by primary key -- not just an unfiltered
    listing -- must come back empty, the same guarantee `DocumentRepository.
    get_by_id` relies on RLS to back up."""
    session = await app_session(app_engine, company_id=two_companies["a"]["company_id"])
    try:
        row = (
            await session.execute(
                text("SELECT id FROM documents WHERE id = :doc_id"),
                {"doc_id": two_companies["b"]["document_id"]},
            )
        ).scalar_one_or_none()
    finally:
        await session.close()

    assert row is None


async def test_insert_with_a_different_companys_id_is_rejected(app_engine, two_companies):
    """WITH CHECK, not just USING: a session scoped to company A must not be able
    to *write* a row claiming to belong to company B, even if it supplies A's own
    valid user_id as the owner."""
    session = await app_session(app_engine, company_id=two_companies["a"]["company_id"])
    try:
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO units (id, company_id, name, description, is_active, created_at, updated_at) "
                    "VALUES ('rls-isolation-test-unit', :bad_cid, 'Sneaky Unit', 'desc', true, now(), now())"
                ),
                {"bad_cid": two_companies["b"]["company_id"]},
            )
    finally:
        await session.rollback()
        await session.close()


async def test_root_scope_reads_across_both_companies(app_engine, two_companies):
    """A root subject, scoped in via app.is_root, is the one legitimate way to
    cross the tenant boundary -- see engine.authorize's tenant gate for the
    application-level counterpart of this same rule."""
    session = await app_session(app_engine, company_id=None, is_root=True)
    try:
        rows = set((await session.execute(text("SELECT id FROM documents"))).scalars().all())
    finally:
        await session.close()

    assert two_companies["a"]["document_id"] in rows
    assert two_companies["b"]["document_id"] in rows


async def test_wrong_company_id_guc_also_sees_zero_rows(app_engine, two_companies):
    """Not just "no GUC" -- an *incorrect* one (e.g. a stale/mismatched claim)
    must fail exactly the same way, not fall back to anything more permissive."""
    session = await app_session(app_engine, company_id="not-a-real-company-id")
    try:
        count = (await session.execute(text("SELECT count(*) FROM documents"))).scalar_one()
    finally:
        await session.close()

    assert count == 0
