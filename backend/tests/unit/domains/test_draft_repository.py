import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.repository import DraftRepository


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def repo(mock_session):
    return DraftRepository(mock_session)


def _draft(**overrides) -> DraftModel:
    defaults = dict(
        id="draft-1",
        user_id=None,
        session_id="session-1",
        document_id=None,
        version=1,
        parent_draft_id=None,
        content="İlk taslak metni.",
        correspondence_type="response_letter",
        routed_unit=None,
        status="COMPLETED",
        confidence_score=90.0,
        instructions="Kullanıcı İsteği: ...",
        is_deleted=False,
    )
    defaults.update(overrides)
    return DraftModel(**defaults)


@pytest.mark.asyncio
async def test_get_latest_for_session_returns_none_when_nothing_exists(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    draft = await repo.get_latest_for_session("nonexistent")

    assert draft is None
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_latest_for_session_returns_the_row(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = _draft()
    mock_session.execute.return_value = mock_result

    draft = await repo.get_latest_for_session("session-1")

    assert draft is not None
    assert draft.content == "İlk taslak metni."


@pytest.mark.asyncio
async def test_create_version_starts_at_one_with_no_parent(repo, mock_session):
    draft = await repo.create_version(session_id="session-1", content="Yeni taslak.")

    assert draft.version == 1
    assert draft.parent_draft_id is None
    mock_session.add.assert_called_once_with(draft)
    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_create_version_increments_and_chains_to_its_parent(repo, mock_session):
    parent = _draft(id="draft-1", version=3)

    child = await repo.create_version(
        session_id="session-1", content="Revize edilmiş taslak.", parent=parent
    )

    assert child.version == 4
    assert child.parent_draft_id == "draft-1"


@pytest.mark.asyncio
async def test_create_version_carries_every_field_through(repo, mock_session):
    draft = await repo.create_version(
        session_id="session-1",
        content="Metin.",
        user_id="user-1",
        document_id="uploads/doc.pdf",
        correspondence_type="cover_letter",
        routed_unit="Hukuk Müşavirliği",
        status="NEEDS_HUMAN_APPROVAL",
        confidence_score=55.0,
        instructions="Talimat.",
    )

    assert draft.user_id == "user-1"
    assert draft.document_id == "uploads/doc.pdf"
    assert draft.correspondence_type == "cover_letter"
    assert draft.routed_unit == "Hukuk Müşavirliği"
    assert draft.status == "NEEDS_HUMAN_APPROVAL"
    assert draft.confidence_score == 55.0
    assert draft.instructions == "Talimat."


@pytest.mark.asyncio
async def test_list_versions_for_session_orders_oldest_first(repo, mock_session):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [
        _draft(id="d1", version=1),
        _draft(id="d2", version=2, parent_draft_id="d1"),
    ]
    mock_session.execute.return_value = mock_result

    versions = await repo.list_versions_for_session("session-1")

    assert [v.version for v in versions] == [1, 2]


@pytest.mark.asyncio
async def test_get_by_id_excludes_soft_deleted_rows_via_the_query_filter(repo, mock_session):
    """Whether a returned row is actually excluded is the query's job (tested
    against a real DB by the migration/e2e path); this locks that the
    repository always applies the is_deleted filter rather than trusting
    every caller to remember it."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    draft = await repo.get_by_id("draft-1")

    assert draft is None
    call_args = mock_session.execute.call_args
    compiled = str(call_args.args[0])
    assert "is_deleted" in compiled
