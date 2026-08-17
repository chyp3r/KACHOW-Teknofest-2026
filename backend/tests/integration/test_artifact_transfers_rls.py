"""Cross-company isolation for artifact_transfers/artifact_transfer_intents,
enforced by Postgres itself via the `kachow_app` role.

Same shape as `test_messaging_rls_isolation.py` -- every query here goes
through `app_engine` (the restricted role) with GUCs set directly via
`app_session`, no repository, no FastAPI, no mocks.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import app_session

pytestmark = pytest.mark.integration


async def test_company_a_cannot_see_company_bs_artifact_transfer(app_engine, two_companies):
    session = await app_session(app_engine, company_id=two_companies["a"]["company_id"])
    try:
        row = (
            await session.execute(
                text("SELECT id FROM artifact_transfers WHERE id = :tid"),
                {"tid": two_companies["b"]["artifact_transfer_id"]},
            )
        ).scalar_one_or_none()
    finally:
        await session.close()

    assert row is None


async def test_company_a_cannot_see_company_bs_transfer_intent(app_engine, two_companies):
    session = await app_session(app_engine, company_id=two_companies["a"]["company_id"])
    try:
        row = (
            await session.execute(
                text("SELECT id FROM artifact_transfer_intents WHERE id = :tid"),
                {"tid": two_companies["b"]["artifact_transfer_intent_id"]},
            )
        ).scalar_one_or_none()
    finally:
        await session.close()

    assert row is None


async def test_company_a_insert_into_artifact_transfers_rejects_company_bs_id(app_engine, two_companies):
    """WITH CHECK, not just USING: a session scoped to company A must not
    be able to *write* an artifact_transfers row claiming to belong to
    company B."""
    session = await app_session(app_engine, company_id=two_companies["a"]["company_id"])
    try:
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO artifact_transfers (id, company_id, artifact_kind, source_artifact_id, "
                    "sender_id, recipient_id, channel, ai_suggested, cross_unit, confirmed_by_user, "
                    "policy_decision, status, created_at, updated_at) "
                    "VALUES ('rls-isolation-test-transfer', :bad_cid, 'draft', :did, :uid, :uid, "
                    "'chat', false, false, true, 'permit', 'executed', now(), now())"
                ),
                {
                    "bad_cid": two_companies["b"]["company_id"],
                    "did": two_companies["a"]["draft_id"],
                    "uid": two_companies["a"]["user_id"],
                },
            )
    finally:
        await session.rollback()
        await session.close()


async def test_root_scope_reads_artifact_transfers_across_both_companies(app_engine, two_companies):
    session = await app_session(app_engine, company_id=None, is_root=True)
    try:
        rows = set((await session.execute(text("SELECT id FROM artifact_transfers"))).scalars().all())
    finally:
        await session.close()

    assert two_companies["a"]["artifact_transfer_id"] in rows
    assert two_companies["b"]["artifact_transfer_id"] in rows


async def test_no_guc_set_sees_zero_artifact_transfer_rows(app_engine, two_companies):
    session = await app_session(app_engine, company_id=None, is_root=False)
    try:
        count = (await session.execute(text("SELECT count(*) FROM artifact_transfers"))).scalar_one()
    finally:
        await session.close()

    assert count == 0
