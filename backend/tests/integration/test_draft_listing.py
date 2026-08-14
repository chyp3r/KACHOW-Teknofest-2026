"""Regression coverage for a real bug in DraftRepository.list_drafts's
session-collapsing subquery, found while live-validating Faz 5's accept-a-
shared-draft feature (DraftShareService.respond).

`session_id IS NULL` marks a "direct" draft with no chat session (see
DraftModel's own docstring). SQL's three-valued logic makes `NULL = NULL`
evaluate to `NULL`, not `TRUE` -- a naive `session_id == session_id` join
predicate therefore drops every such draft from the listing entirely, and a
bare `GROUP BY session_id` (which *does* bucket NULLs together, unlike a
join predicate) would collapse every unrelated session-less draft in the
whole system into a single shared "latest version" once more than one of
them exceeds version 1 -- which only became possible once an accepted share
could fork a session-less copy at version >= 2. Neither of those is a
mocked-session-testable property; this needs a real Postgres to exercise
real NULL comparison semantics, which is why this lives in
`tests/integration/`, not `tests/unit/`.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domains.drafts.repository import DraftRepository

pytestmark = pytest.mark.integration


async def _insert_draft(session, *, id, company_id, user_id, version, parent_draft_id=None):
    await session.execute(
        text(
            "INSERT INTO drafts (id, company_id, user_id, session_id, version, content, "
            "parent_draft_id, is_deleted, created_at, updated_at) "
            "VALUES (:id, :cid, :uid, NULL, :version, 'içerik', :parent, false, now(), now())"
        ),
        {"id": id, "cid": company_id, "uid": user_id, "version": version, "parent": parent_draft_id},
    )


async def test_list_drafts_shows_every_independent_session_less_draft(owner_engine, two_companies):
    """Two unrelated direct (session_id=NULL) drafts by the same user must
    both appear -- not collapse to zero (the pre-fix bug: NULL = NULL is
    NULL, not TRUE) or to just one of them."""
    company_id = two_companies["a"]["company_id"]
    user_id = two_companies["a"]["user_id"]
    session_maker = async_sessionmaker(bind=owner_engine, class_=AsyncSession, expire_on_commit=False)

    draft_a, draft_b = f"listing-test-{uuid4().hex}", f"listing-test-{uuid4().hex}"
    async with session_maker() as session:
        await _insert_draft(session, id=draft_a, company_id=company_id, user_id=user_id, version=1)
        await _insert_draft(session, id=draft_b, company_id=company_id, user_id=user_id, version=1)
        await session.commit()

        repo = DraftRepository(session)
        drafts = await repo.list_drafts(company_id=company_id, user_id=user_id, limit=1000)

    listed_ids = {d.id for d in drafts}
    assert draft_a in listed_ids
    assert draft_b in listed_ids


async def test_list_drafts_does_not_let_a_higher_version_fork_hide_an_unrelated_draft(
    owner_engine, two_companies
):
    """The bug this test pins: before the fix, a single session-less draft
    at version 2+ (an accepted share's fork -- see DraftShareService.respond)
    would dominate the global `MAX(version)` for the whole NULL-session
    group and hide every *other* session-less draft in the system, not just
    older versions of its own chain."""
    company_id = two_companies["a"]["company_id"]
    user_id = two_companies["a"]["user_id"]
    session_maker = async_sessionmaker(bind=owner_engine, class_=AsyncSession, expire_on_commit=False)

    unrelated_draft = f"listing-test-{uuid4().hex}"
    root_draft = f"listing-test-{uuid4().hex}"
    forked_draft = f"listing-test-{uuid4().hex}"
    async with session_maker() as session:
        await _insert_draft(session, id=unrelated_draft, company_id=company_id, user_id=user_id, version=1)
        await _insert_draft(session, id=root_draft, company_id=company_id, user_id=user_id, version=1)
        await _insert_draft(
            session, id=forked_draft, company_id=company_id, user_id=user_id, version=2,
            parent_draft_id=root_draft,
        )
        await session.commit()

        repo = DraftRepository(session)
        drafts = await repo.list_drafts(company_id=company_id, user_id=user_id, limit=1000)

    listed_ids = {d.id for d in drafts}
    assert unrelated_draft in listed_ids
