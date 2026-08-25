import pytest
from unittest.mock import AsyncMock
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.repository import DraftRepository


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def repo(mock_session):
    return DraftRepository(mock_session)


@pytest.mark.asyncio
async def test_soft_delete_session_marks_every_version_in_the_chain(repo, mock_session):
    """`list_drafts` only ever shows a session's latest version -- soft-deleting
    just that one row would resurrect the previous version as the new listing,
    so the whole chain must be marked in one statement."""
    await repo.soft_delete_session("session-1")

    mock_session.execute.assert_awaited_once()
    statement = mock_session.execute.await_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "drafts" in compiled
    assert "session-1" in compiled
    assert "is_deleted" in compiled
    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_soft_delete_marks_a_single_draft(repo, mock_session):
    await repo.soft_delete("draft-1")

    mock_session.execute.assert_awaited_once()
    statement = mock_session.execute.await_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "draft-1" in compiled
    assert "is_deleted" in compiled
    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_destination_mutates_the_row_in_place_and_flushes(repo, mock_session):
    draft = DraftModel(
        id="draft-1", company_id="company-1", version=1, content="içerik",
        destination="Eski Birim", destination_unit_id="unit-old",
        destination_justification="Eski gerekçe.",
    )

    updated = await repo.update_destination(
        draft,
        destination="Yeni Birim",
        destination_unit_id="unit-new",
        destination_justification="Yeni gerekçe.",
    )

    assert updated is draft
    assert draft.destination == "Yeni Birim"
    assert draft.destination_unit_id == "unit-new"
    assert draft.destination_justification == "Yeni gerekçe."
    mock_session.flush.assert_awaited_once()
    mock_session.refresh.assert_awaited_once_with(draft, attribute_names=["updated_at"])
    # No `db.execute()` -- this mutates the already-loaded ORM object and
    # relies on the caller's own commit/autoflush, same as
    # `create_version`'s `self.db.add`, not a raw UPDATE statement.
    mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_update_destination_leaves_the_justification_untouched_when_omitted(repo, mock_session):
    draft = DraftModel(
        id="draft-1", company_id="company-1", version=1, content="içerik",
        destination_justification="Orijinal gerekçe.",
    )

    await repo.update_destination(
        draft, destination="Yeni Birim", destination_unit_id=None, destination_justification=None
    )

    assert draft.destination_justification == "Orijinal gerekçe."


@pytest.mark.asyncio
async def test_approve_review_marks_only_the_human_gate_complete(repo, mock_session):
    draft = DraftModel(
        id="draft-1",
        company_id="company-1",
        version=1,
        content="içerik",
        status="NEEDS_HUMAN_APPROVAL",
        requires_human_approval=True,
        missing_information=[{"key": "sayi", "label": "Sayı"}],
    )

    updated = await repo.approve_review(draft)

    assert updated is draft
    assert draft.requires_human_approval is False
    assert draft.status == "NEEDS_INPUT"
    assert draft.missing_information == [{"key": "sayi", "label": "Sayı"}]
    mock_session.flush.assert_awaited_once()
    mock_session.refresh.assert_awaited_once_with(draft, attribute_names=["updated_at"])


@pytest.mark.asyncio
async def test_attach_session_turns_a_direct_draft_into_a_revision_parent(repo, mock_session):
    draft = DraftModel(
        id="draft-direct", company_id="company-1", session_id=None, version=1, content="içerik"
    )

    attached = await repo.attach_session(draft, "user-1:web:revision")

    assert attached is draft
    assert draft.session_id == "user-1:web:revision"
    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_attach_session_never_moves_an_existing_draft_chain(repo, mock_session):
    draft = DraftModel(
        id="draft-1", company_id="company-1", session_id="original", version=1, content="içerik"
    )

    attached = await repo.attach_session(draft, "different")

    assert attached.session_id == "original"
    mock_session.flush.assert_not_called()


def test_soft_delete_statement_shape_matches_the_model():
    """Sanity check that the update() target/column names used above are
    real DraftModel attributes, not typo'd strings that would only fail at
    runtime against a live database."""
    statement = update(DraftModel).where(DraftModel.session_id == "x").values(is_deleted=True)
    assert statement.table.name == "drafts"
