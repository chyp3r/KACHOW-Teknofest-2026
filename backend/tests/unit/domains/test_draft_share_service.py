from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.domains.drafts.draft_share_service import DraftShareService
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.model.draft_share_model import DraftShareModel
from app.domains.drafts.schema.draft_share_schema import DraftSendRequest
from app.domains.units.model.unit_model import UnitModel
from app.domains.users.model.user_model import UserModel


def _user(**overrides) -> UserModel:
    fields = dict(
        id="emp-1", company_id="company-1", username="emp1", email="emp1@example.com",
        role="employee", clearance_level="hizmete_ozel", is_active=True, is_deleted=False,
        hashed_password="x", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return UserModel(**fields)


def _draft(**overrides) -> DraftModel:
    fields = dict(
        id="draft-1", company_id="company-1", user_id="emp-1", session_id=None,
        document_id=None, version=1, content="içerik", destination=None, correspondence_type=None,
        is_deleted=False, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return DraftModel(**fields)


def _share(**overrides) -> DraftShareModel:
    fields = dict(
        id="share-1", company_id="company-1", draft_id="draft-1", sender_id="emp-1",
        recipient_id="emp-2", suggested_unit_id=None, message=None, status="sent",
        responded_at=None, response_note=None,
    )
    fields.update(overrides)
    return DraftShareModel(**fields)


@pytest.fixture
def share_repo():
    return AsyncMock()


@pytest.fixture
def draft_repo():
    return AsyncMock()


@pytest.fixture
def user_repo():
    return AsyncMock()


@pytest.fixture
def unit_repo():
    return AsyncMock()


@pytest.fixture
def service(share_repo, draft_repo, user_repo, unit_repo):
    return DraftShareService(share_repo, draft_repo, user_repo, unit_repo)


@pytest.fixture(autouse=True)
def _no_real_event_publish(monkeypatch):
    """Every send/respond call publishes a domain event -- isolate these unit
    tests from the real process-wide `event_bus` (whose listeners, if any
    got registered by another test module, would try to open a real DB
    session -- see `app.events.subscribers._write_notification`)."""
    published = AsyncMock()
    monkeypatch.setattr("app.domains.drafts.draft_share_service.event_bus.publish", published)
    return published


async def test_send_404s_when_draft_missing(service, draft_repo):
    draft_repo.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await service.send("draft-1", _user(), DraftSendRequest(recipient_ids=["emp-2"]), "company-1")


async def test_send_denies_a_non_owner_employee(service, draft_repo):
    draft_repo.get_by_id.return_value = _draft(user_id="someone-else")

    with pytest.raises(AuthorizationException):
        await service.send("draft-1", _user(id="emp-1"), DraftSendRequest(recipient_ids=["emp-2"]), "company-1")


async def test_send_allows_an_admin_that_does_not_own_the_draft(service, draft_repo, user_repo, share_repo):
    draft_repo.get_by_id.return_value = _draft(user_id="someone-else")
    user_repo.get_by_id_in_company.return_value = _user(id="emp-2")
    share_repo.create.side_effect = lambda share: share

    shares = await service.send(
        "draft-1", _user(id="admin-1", role="admin"), DraftSendRequest(recipient_ids=["emp-2"]), "company-1"
    )

    assert len(shares) == 1


async def test_send_404s_on_a_recipient_outside_the_company(service, draft_repo, user_repo):
    draft_repo.get_by_id.return_value = _draft()
    user_repo.get_by_id_in_company.return_value = None

    with pytest.raises(NotFoundException):
        await service.send("draft-1", _user(), DraftSendRequest(recipient_ids=["ghost"]), "company-1")


async def test_send_creates_one_share_per_recipient_and_publishes(
    service, draft_repo, user_repo, share_repo, _no_real_event_publish
):
    draft_repo.get_by_id.return_value = _draft()
    user_repo.get_by_id_in_company.side_effect = [_user(id="emp-2"), _user(id="emp-3")]
    share_repo.create.side_effect = lambda share: share

    shares = await service.send(
        "draft-1", _user(), DraftSendRequest(recipient_ids=["emp-2", "emp-3"], message="bkz"), "company-1"
    )

    assert {s.recipient_id for s in shares} == {"emp-2", "emp-3"}
    assert all(s.message == "bkz" for s in shares)
    assert _no_real_event_publish.await_count == 2


async def test_send_resolves_suggested_unit_from_draft_destination(service, draft_repo, user_repo, unit_repo, share_repo):
    draft_repo.get_by_id.return_value = _draft(destination="Mali İşler")
    unit_repo.get_by_name.return_value = UnitModel(
        id="unit-1", company_id="company-1", name="Mali İşler", description="x", is_active=True
    )
    user_repo.get_by_id_in_company.return_value = _user(id="emp-2")
    share_repo.create.side_effect = lambda share: share

    shares = await service.send("draft-1", _user(), DraftSendRequest(recipient_ids=["emp-2"]), "company-1")

    assert shares[0].suggested_unit_id == "unit-1"


async def test_send_leaves_suggested_unit_null_when_destination_has_no_match(
    service, draft_repo, user_repo, unit_repo, share_repo
):
    draft_repo.get_by_id.return_value = _draft(destination="Bilinmeyen Birim")
    unit_repo.get_by_name.return_value = None
    user_repo.get_by_id_in_company.return_value = _user(id="emp-2")
    share_repo.create.side_effect = lambda share: share

    shares = await service.send("draft-1", _user(), DraftSendRequest(recipient_ids=["emp-2"]), "company-1")

    assert shares[0].suggested_unit_id is None


async def test_mark_read_denies_a_non_recipient(service, share_repo, draft_repo):
    share_repo.get_by_id.return_value = _share(recipient_id="emp-2")
    draft_repo.get_by_id.return_value = _draft()

    with pytest.raises(AuthorizationException):
        await service.mark_read("share-1", "company-1", _user(id="emp-3"))


async def test_respond_denies_a_non_recipient(service, share_repo, draft_repo):
    share_repo.get_by_id.return_value = _share(recipient_id="emp-2")
    draft_repo.get_by_id.return_value = _draft()

    with pytest.raises(AuthorizationException):
        await service.respond("share-1", "company-1", _user(id="emp-3"), "accepted", None)


async def test_respond_denies_when_already_resolved(service, share_repo, draft_repo):
    share_repo.get_by_id.return_value = _share(recipient_id="emp-1", status="accepted")
    draft_repo.get_by_id.return_value = _draft()

    with pytest.raises(AuthorizationException):
        await service.respond("share-1", "company-1", _user(id="emp-1"), "accepted", None)


async def test_accept_forks_a_new_draft_version_owned_by_the_recipient(
    service, share_repo, draft_repo, _no_real_event_publish
):
    share = _share(recipient_id="emp-1", status="sent")
    share_repo.get_by_id.return_value = share
    share_repo.respond.side_effect = lambda s, status, note: s
    original = _draft(id="draft-1", user_id="sender-1", content="orijinal içerik")
    draft_repo.get_by_id.return_value = original

    await service.respond("share-1", "company-1", _user(id="emp-1"), "accepted", "tamam")

    draft_repo.create_version.assert_awaited_once()
    call_kwargs = draft_repo.create_version.await_args.kwargs
    assert call_kwargs["user_id"] == "emp-1"
    assert call_kwargs["parent"] is original
    assert call_kwargs["content"] == "orijinal içerik"
    assert _no_real_event_publish.await_count == 1


async def test_reject_does_not_fork_a_new_version(service, share_repo, draft_repo):
    share = _share(recipient_id="emp-1", status="sent")
    share_repo.get_by_id.return_value = share
    share_repo.respond.side_effect = lambda s, status, note: s
    draft_repo.get_by_id.return_value = _draft()

    await service.respond("share-1", "company-1", _user(id="emp-1"), "rejected", "olmadı")

    draft_repo.create_version.assert_not_awaited()


async def test_withdraw_denies_a_non_sender_employee(service, share_repo, draft_repo):
    share_repo.get_by_id.return_value = _share(sender_id="emp-1", recipient_id="emp-2")
    draft_repo.get_by_id.return_value = _draft()

    with pytest.raises(AuthorizationException):
        await service.withdraw("share-1", "company-1", _user(id="emp-2"))


async def test_withdraw_denies_a_non_sent_share(service, share_repo, draft_repo):
    share_repo.get_by_id.return_value = _share(sender_id="emp-1", status="accepted")
    draft_repo.get_by_id.return_value = _draft()

    with pytest.raises(AuthorizationException):
        await service.withdraw("share-1", "company-1", _user(id="emp-1"))


async def test_withdraw_succeeds_for_the_sender(service, share_repo, draft_repo):
    share_repo.get_by_id.return_value = _share(sender_id="emp-1", status="sent")
    draft_repo.get_by_id.return_value = _draft()
    share_repo.withdraw.side_effect = lambda s: s

    result = await service.withdraw("share-1", "company-1", _user(id="emp-1"))

    assert result is not None
    share_repo.withdraw.assert_awaited_once()
