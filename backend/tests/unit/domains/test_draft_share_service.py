from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.domains.drafts.draft_share_service import DraftShareService
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.model.draft_share_model import DraftShareModel
from app.domains.drafts.schema.draft_share_schema import DraftSendRequest
from app.domains.transfers.model.transfer_model import ArtifactTransferModel
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
        document_id=None, version=1, content="içerik", destination=None,
        destination_unit_id=None, destination_justification=None, correspondence_type=None,
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


def _transfer(**overrides) -> ArtifactTransferModel:
    fields = dict(
        id="transfer-1", company_id="company-1", artifact_kind="draft", source_artifact_id="draft-1",
        source_version=1, snapshot_ref="draft-2", sender_id="emp-1", recipient_id="emp-2",
        channel="rest", status="executed", policy_decision="permit",
    )
    fields.update(overrides)
    return ArtifactTransferModel(**fields)


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
def transfer_service():
    """`ArtifactTransferService` is now injected, not built by
    `DraftShareService` itself -- see its own docstring. `execute`
    defaults to succeeding; individual tests override `side_effect` to
    exercise the NotFound/Authorization paths it's responsible for."""
    service = AsyncMock()
    service.execute.side_effect = lambda cmd: _transfer(recipient_id=cmd.recipient_id)
    return service


@pytest.fixture
def service(share_repo, draft_repo, user_repo, transfer_service):
    return DraftShareService(share_repo, draft_repo, user_repo, transfer_service)


@pytest.fixture(autouse=True)
def _no_real_event_publish(monkeypatch):
    """`respond()` still publishes `DraftShareRespondedEvent` directly --
    isolate these unit tests from the real process-wide `event_bus` (whose
    listeners, if any got registered by another test module, would try to
    open a real DB session -- see `app.events.subscribers._write_notification`).
    `send()` itself no longer publishes anything (that now happens inside
    `ArtifactTransferService.execute`, mocked separately via
    `transfer_service` above), so this fixture is only exercised by the
    `respond`-path tests below.
    """
    published = AsyncMock()
    monkeypatch.setattr("app.domains.drafts.draft_share_service.event_bus.publish", published)
    return published


async def test_send_404s_when_draft_missing(service, draft_repo):
    draft_repo.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await service.send("draft-1", _user(), DraftSendRequest(recipient_ids=["emp-2"]), "company-1")


async def test_send_propagates_a_transfer_authorization_denial(service, draft_repo, transfer_service):
    """`send` no longer authorizes anything itself -- `ArtifactTransferService.
    execute` does (see its own docstring), so a non-owner employee is
    denied there, and `send` must not swallow that."""
    draft_repo.get_by_id.return_value = _draft(user_id="someone-else")
    transfer_service.execute.side_effect = AuthorizationException(message="Bu taslağı gönderme izniniz yok.")

    with pytest.raises(AuthorizationException):
        await service.send("draft-1", _user(id="emp-1"), DraftSendRequest(recipient_ids=["emp-2"]), "company-1")


async def test_send_allows_an_admin_that_does_not_own_the_draft(service, draft_repo, share_repo, transfer_service):
    draft_repo.get_by_id.return_value = _draft(user_id="someone-else")
    share_repo.create.side_effect = lambda share: share

    shares = await service.send(
        "draft-1", _user(id="admin-1", role="admin"), DraftSendRequest(recipient_ids=["emp-2"]), "company-1"
    )

    assert len(shares) == 1
    transfer_service.execute.assert_awaited_once()


async def test_send_propagates_a_recipient_not_found_from_the_transfer_service(
    service, draft_repo, transfer_service
):
    draft_repo.get_by_id.return_value = _draft()
    transfer_service.execute.side_effect = NotFoundException(message="Kullanıcı bulunamadı.")

    with pytest.raises(NotFoundException):
        await service.send("draft-1", _user(), DraftSendRequest(recipient_ids=["ghost"]), "company-1")


async def test_send_creates_one_share_per_recipient_and_calls_transfer_once_each(
    service, draft_repo, share_repo, transfer_service
):
    draft_repo.get_by_id.return_value = _draft()
    share_repo.create.side_effect = lambda share: share

    shares = await service.send(
        "draft-1", _user(), DraftSendRequest(recipient_ids=["emp-2", "emp-3"], message="bkz"), "company-1"
    )

    assert {s.recipient_id for s in shares} == {"emp-2", "emp-3"}
    assert all(s.message == "bkz" for s in shares)
    assert transfer_service.execute.await_count == 2


async def test_send_passes_the_draft_version_through_to_the_transfer_command(
    service, draft_repo, share_repo, transfer_service
):
    draft_repo.get_by_id.return_value = _draft(version=3)
    share_repo.create.side_effect = lambda share: share

    await service.send("draft-1", _user(), DraftSendRequest(recipient_ids=["emp-2"]), "company-1")

    cmd = transfer_service.execute.await_args.args[0]
    assert cmd.source_version == 3
    assert cmd.artifact_kind == "draft"
    assert cmd.channel == "rest"


async def test_send_carries_the_draft_s_already_resolved_destination_unit(
    service, draft_repo, share_repo, transfer_service
):
    """`suggested_unit_id` is a straight passthrough of `drafts.
    destination_unit_id` now -- resolved once, at draft-write time, by
    `draft_recorder.record_draft`; `send` no longer re-resolves a unit
    name at send time."""
    draft_repo.get_by_id.return_value = _draft(destination_unit_id="unit-1")
    share_repo.create.side_effect = lambda share: share

    shares = await service.send("draft-1", _user(), DraftSendRequest(recipient_ids=["emp-2"]), "company-1")

    assert shares[0].suggested_unit_id == "unit-1"


async def test_send_leaves_suggested_unit_null_when_the_draft_was_never_routed(
    service, draft_repo, share_repo, transfer_service
):
    draft_repo.get_by_id.return_value = _draft(destination_unit_id=None)
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


async def test_accept_no_longer_forks_a_draft_version(service, share_repo, draft_repo):
    """The double-fork bug this change fixes (see `respond`'s own
    docstring): the recipient already got their own copy at *send* time,
    via `ArtifactTransferService.execute`'s fork -- accepting must not
    fork a second one."""
    share = _share(recipient_id="emp-1", status="sent")
    share_repo.get_by_id.return_value = share
    share_repo.respond.side_effect = lambda s, status, note: s
    draft_repo.get_by_id.return_value = _draft(id="draft-1", user_id="sender-1", content="orijinal içerik")

    await service.respond("share-1", "company-1", _user(id="emp-1"), "accepted", "tamam")

    draft_repo.create_version.assert_not_awaited()


async def test_reject_does_not_fork_a_new_version(service, share_repo, draft_repo):
    share = _share(recipient_id="emp-1", status="sent")
    share_repo.get_by_id.return_value = share
    share_repo.respond.side_effect = lambda s, status, note: s
    draft_repo.get_by_id.return_value = _draft()

    await service.respond("share-1", "company-1", _user(id="emp-1"), "rejected", "olmadı")

    draft_repo.create_version.assert_not_awaited()


async def test_respond_still_publishes_the_responded_event(
    service, share_repo, draft_repo, _no_real_event_publish
):
    share = _share(recipient_id="emp-1", status="sent")
    share_repo.get_by_id.return_value = share
    share_repo.respond.side_effect = lambda s, status, note: s
    draft_repo.get_by_id.return_value = _draft()

    await service.respond("share-1", "company-1", _user(id="emp-1"), "accepted", "tamam")

    _no_real_event_publish.assert_awaited_once()


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
