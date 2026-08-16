"""Cross-company isolation for conversations/participants/messages/favorites,
enforced by Postgres itself via the `kachow_app` role.

Same shape as `test_rls_isolation.py` -- every query here goes through
`app_engine` (the restricted role) with GUCs set directly via `app_session`,
no repository, no FastAPI, no mocks.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import app_session

pytestmark = pytest.mark.integration


async def test_company_a_cannot_see_company_bs_conversation(app_engine, two_companies):
    session = await app_session(app_engine, company_id=two_companies["a"]["company_id"])
    try:
        row = (
            await session.execute(
                text("SELECT id FROM conversations WHERE id = :cid"),
                {"cid": two_companies["b"]["conversation_id"]},
            )
        ).scalar_one_or_none()
    finally:
        await session.close()

    assert row is None


async def test_company_a_cannot_see_company_bs_conversation_participant(app_engine, two_companies):
    session = await app_session(app_engine, company_id=two_companies["a"]["company_id"])
    try:
        row = (
            await session.execute(
                text("SELECT id FROM conversation_participants WHERE id = :pid"),
                {"pid": two_companies["b"]["conversation_participant_id"]},
            )
        ).scalar_one_or_none()
    finally:
        await session.close()

    assert row is None


async def test_company_a_cannot_see_company_bs_conversation_message(app_engine, two_companies):
    session = await app_session(app_engine, company_id=two_companies["a"]["company_id"])
    try:
        row = (
            await session.execute(
                text("SELECT id FROM conversation_messages WHERE id = :mid"),
                {"mid": two_companies["b"]["conversation_message_id"]},
            )
        ).scalar_one_or_none()
    finally:
        await session.close()

    assert row is None


async def test_company_a_cannot_see_company_bs_favorite(app_engine, two_companies):
    session = await app_session(app_engine, company_id=two_companies["a"]["company_id"])
    try:
        row = (
            await session.execute(
                text("SELECT id FROM user_favorites WHERE id = :fid"),
                {"fid": two_companies["b"]["favorite_id"]},
            )
        ).scalar_one_or_none()
    finally:
        await session.close()

    assert row is None


async def test_company_a_insert_into_conversations_rejects_company_bs_id(app_engine, two_companies):
    """WITH CHECK, not just USING: a session scoped to company A must not be
    able to *write* a conversation claiming to belong to company B."""
    session = await app_session(app_engine, company_id=two_companies["a"]["company_id"])
    try:
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO conversations (id, company_id, kind, created_by, is_archived, "
                    "created_at, updated_at) "
                    "VALUES ('rls-isolation-test-conv', :bad_cid, 'group', :uid, false, now(), now())"
                ),
                {"bad_cid": two_companies["b"]["company_id"], "uid": two_companies["a"]["user_id"]},
            )
    finally:
        await session.rollback()
        await session.close()


async def test_company_a_insert_into_user_favorites_rejects_company_bs_id(app_engine, two_companies):
    session = await app_session(app_engine, company_id=two_companies["a"]["company_id"])
    try:
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO user_favorites (id, company_id, owner_user_id, favorite_user_id, "
                    "created_at, updated_at) "
                    "VALUES ('rls-isolation-test-favorite', :bad_cid, :uid, :uid, now(), now())"
                ),
                {"bad_cid": two_companies["b"]["company_id"], "uid": two_companies["a"]["user_id"]},
            )
    finally:
        await session.rollback()
        await session.close()


async def test_root_scope_reads_conversations_across_both_companies(app_engine, two_companies):
    session = await app_session(app_engine, company_id=None, is_root=True)
    try:
        rows = set((await session.execute(text("SELECT id FROM conversations"))).scalars().all())
    finally:
        await session.close()

    assert two_companies["a"]["conversation_id"] in rows
    assert two_companies["b"]["conversation_id"] in rows


async def test_no_guc_set_sees_zero_conversation_rows(app_engine, two_companies):
    session = await app_session(app_engine, company_id=None, is_root=False)
    try:
        count = (await session.execute(text("SELECT count(*) FROM conversations"))).scalar_one()
    finally:
        await session.close()

    assert count == 0
