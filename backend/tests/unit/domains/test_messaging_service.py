from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.domains.messaging.model.conversation_message_model import ConversationMessageModel
from app.domains.messaging.model.conversation_model import ConversationModel
from app.domains.messaging.model.conversation_participant_model import ConversationParticipantModel
from app.domains.messaging.service import MAX_GROUP_PARTICIPANTS, ConversationService, _dm_key
from app.domains.users.model.user_model import UserModel


def _user(**overrides) -> UserModel:
    fields = dict(
        id="emp-1", company_id="company-1", username="emp1", email="emp1@example.com",
        role="employee", clearance_level="hizmete_ozel", is_active=True, is_deleted=False,
        hashed_password="x", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return UserModel(**fields)


def _conversation(**overrides) -> ConversationModel:
    fields = dict(
        id="conv-1", company_id="company-1", kind="dm", title=None, dm_key=_dm_key("emp-1", "emp-2"),
        created_by="emp-1", last_message_at=None, is_archived=False,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return ConversationModel(**fields)


def _participant(**overrides) -> ConversationParticipantModel:
    fields = dict(
        id="part-1", company_id="company-1", conversation_id="conv-1", user_id="emp-1",
        role_in_conversation="member", left_at=None, last_read_message_id=None, muted_at=None,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return ConversationParticipantModel(**fields)


def _message(**overrides) -> ConversationMessageModel:
    fields = dict(
        id="msg-1", company_id="company-1", conversation_id="conv-1", sender_id="emp-1",
        kind="text", body="merhaba", artifact_transfer_id=None, deleted_at=None,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return ConversationMessageModel(**fields)


@pytest.fixture
def conversation_repo():
    return AsyncMock()


@pytest.fixture
def participant_repo():
    return AsyncMock()


@pytest.fixture
def message_repo():
    return AsyncMock()


@pytest.fixture
def user_repo():
    return AsyncMock()


@pytest.fixture
def service(conversation_repo, participant_repo, message_repo, user_repo):
    return ConversationService(conversation_repo, participant_repo, message_repo, user_repo, cache=None)


@pytest.fixture(autouse=True)
def _no_real_event_publish(monkeypatch):
    """Isolate from the real process-wide `event_bus` -- same reasoning as
    `test_draft_share_service.py`'s own fixture of the same name."""
    published = AsyncMock()
    monkeypatch.setattr("app.domains.messaging.service.event_bus.publish", published)
    return published


# ---------- open_dm ----------


async def test_open_dm_rejects_self(service):
    with pytest.raises(AuthorizationException):
        await service.open_dm("company-1", _user(id="emp-1"), "emp-1")


async def test_open_dm_404s_on_unknown_recipient(service, user_repo):
    user_repo.get_by_id_in_company.return_value = None
    with pytest.raises(NotFoundException):
        await service.open_dm("company-1", _user(id="emp-1"), "emp-2")


async def test_open_dm_is_idempotent(service, user_repo, conversation_repo, participant_repo):
    """A second call with the same pair returns the existing conversation,
    never creates a duplicate row."""
    user_repo.get_by_id_in_company.return_value = _user(id="emp-2", username="emp2")
    existing = _conversation()
    conversation_repo.get_dm.return_value = existing

    result = await service.open_dm("company-1", _user(id="emp-1"), "emp-2")

    assert result is existing
    conversation_repo.create.assert_not_called()
    participant_repo.create_many.assert_not_called()


async def test_open_dm_creates_conversation_and_both_participants(
    service, user_repo, conversation_repo, participant_repo
):
    user_repo.get_by_id_in_company.return_value = _user(id="emp-2", username="emp2")
    conversation_repo.get_dm.return_value = None
    conversation_repo.create.side_effect = lambda c: c

    result = await service.open_dm("company-1", _user(id="emp-1"), "emp-2")

    assert result.kind == "dm"
    assert result.dm_key == _dm_key("emp-1", "emp-2")
    participant_repo.create_many.assert_awaited_once()
    created = participant_repo.create_many.await_args.args[0]
    assert {p.user_id for p in created} == {"emp-1", "emp-2"}


# ---------- create_group ----------


async def test_create_group_requires_at_least_one_other_member(service):
    with pytest.raises(AuthorizationException):
        await service.create_group("company-1", _user(id="emp-1"), "Proje", ["emp-1"])


async def test_create_group_enforces_max_participants(service):
    too_many = [f"emp-{i}" for i in range(MAX_GROUP_PARTICIPANTS + 1)]
    with pytest.raises(AuthorizationException):
        await service.create_group("company-1", _user(id="emp-1"), "Proje", too_many)


async def test_create_group_404s_on_unknown_member(service, user_repo):
    user_repo.get_by_id_in_company.return_value = None
    with pytest.raises(NotFoundException):
        await service.create_group("company-1", _user(id="emp-1"), "Proje", ["emp-2"])


async def test_create_group_owner_is_creator(service, user_repo, conversation_repo, participant_repo):
    user_repo.get_by_id_in_company.return_value = _user(id="emp-2", username="emp2")
    conversation_repo.create.side_effect = lambda c: c

    await service.create_group("company-1", _user(id="emp-1"), "Proje", ["emp-2"])

    created = participant_repo.create_many.await_args.args[0]
    owner_rows = [p for p in created if p.role_in_conversation == "owner"]
    assert len(owner_rows) == 1
    assert owner_rows[0].user_id == "emp-1"


# ---------- read access / send ----------


async def test_get_participant_404s_on_unknown_conversation(service, conversation_repo):
    conversation_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundException):
        await service._get_participant_or_403("conv-1", "company-1", "emp-1")


async def test_get_participant_403s_on_non_participant(service, conversation_repo, participant_repo):
    conversation_repo.get_by_id.return_value = _conversation()
    participant_repo.get.return_value = None
    with pytest.raises(AuthorizationException):
        await service._get_participant_or_403("conv-1", "company-1", "emp-3")


async def test_left_participant_may_still_read(service, conversation_repo, participant_repo):
    conversation_repo.get_by_id.return_value = _conversation()
    left_participant = _participant(left_at=datetime.now(timezone.utc))
    participant_repo.get.return_value = left_participant

    result = await service._get_participant_or_403("conv-1", "company-1", "emp-1")

    assert result is left_participant


async def test_send_text_message_rejects_a_participant_who_left(service, conversation_repo, participant_repo):
    conversation_repo.get_by_id.return_value = _conversation()
    participant_repo.get.return_value = _participant(left_at=datetime.now(timezone.utc))

    with pytest.raises(AuthorizationException):
        await service.send_text_message("conv-1", "company-1", _user(id="emp-1"), "merhaba")


async def test_send_text_message_touches_last_message_and_notifies(
    service, conversation_repo, participant_repo, message_repo
):
    conversation_repo.get_by_id.return_value = _conversation()
    participant_repo.get.return_value = _participant(left_at=None)
    sent = _message()
    message_repo.create.return_value = sent
    participant_repo.list_for_conversation.return_value = [
        _participant(user_id="emp-1"),
        _participant(id="part-2", user_id="emp-2"),
    ]

    result = await service.send_text_message("conv-1", "company-1", _user(id="emp-1", username="emp1"), "merhaba")

    assert result is sent
    conversation_repo.touch_last_message.assert_awaited_once()


async def test_send_text_message_never_notifies_the_sender(
    service, conversation_repo, participant_repo, message_repo, _no_real_event_publish
):
    conversation_repo.get_by_id.return_value = _conversation()
    participant_repo.get.return_value = _participant(left_at=None)
    message_repo.create.return_value = _message()
    participant_repo.list_for_conversation.return_value = [_participant(user_id="emp-1")]

    await service.send_text_message("conv-1", "company-1", _user(id="emp-1", username="emp1"), "merhaba")

    _no_real_event_publish.assert_not_called()


# ---------- participants ----------


async def test_self_leave_does_not_require_owner(service, conversation_repo, participant_repo):
    conversation_repo.get_by_id.return_value = _conversation(kind="group")
    member = _participant(role_in_conversation="member")
    participant_repo.get.return_value = member
    participant_repo.list_for_conversation.return_value = [member]

    await service.remove_participant("conv-1", "company-1", _user(id="emp-1", role="employee"), "emp-1")

    participant_repo.mark_left.assert_awaited_once()


async def test_removing_someone_else_requires_owner_or_bypass(service, conversation_repo, participant_repo):
    conversation_repo.get_by_id.return_value = _conversation(kind="group")
    requester_row = _participant(user_id="emp-1", role_in_conversation="member")
    participant_repo.get.return_value = requester_row
    participant_repo.list_for_conversation.return_value = [requester_row]

    with pytest.raises(AuthorizationException):
        await service.remove_participant(
            "conv-1", "company-1", _user(id="emp-1", role="employee"), "emp-2"
        )


async def test_dm_participants_cannot_be_removed(service, conversation_repo, participant_repo):
    conversation_repo.get_by_id.return_value = _conversation(kind="dm")
    row = _participant()
    participant_repo.get.return_value = row
    participant_repo.list_for_conversation.return_value = [row]

    with pytest.raises(AuthorizationException):
        await service.remove_participant("conv-1", "company-1", _user(id="emp-1"), "emp-1")
