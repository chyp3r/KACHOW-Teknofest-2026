from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.api.exceptions.validation import ValidationException
from app.domains.documents.model.document_model import DocumentModel
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.messaging.model.conversation_message_model import ConversationMessageModel
from app.domains.messaging.model.conversation_model import ConversationModel
from app.domains.transfers.model.transfer_model import ArtifactTransferModel
from app.domains.transfers.policy import TransferPolicyDecision
from app.domains.transfers.service import (
    MAX_GROUP_TRANSFER_RECIPIENTS,
    ArtifactTransferService,
    GroupTransferCommand,
    TransferCommand,
)
from app.domains.users.model.user_model import UserModel
from app.observability import transfer_metrics


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


def _document(**overrides) -> DocumentModel:
    fields = dict(
        id="uploads/doc.pdf", company_id="company-1", owner_id="emp-1", file_name="doc.pdf",
        document_type="", document_type_label="", compliance_status="", summary="",
        sensitivity_level="unmarked", pii_flagged=False,
    )
    fields.update(overrides)
    return DocumentModel(**fields)


@pytest.fixture
def transfer_repo():
    repo = AsyncMock()
    repo.get_by_idempotency_key.return_value = None
    repo.create.side_effect = lambda transfer: transfer
    repo.db = AsyncMock()
    return repo


@pytest.fixture
def draft_repo():
    repo = AsyncMock()
    forked = _draft(id="draft-2", user_id="emp-2")
    repo.create_version.return_value = forked
    return repo


@pytest.fixture
def document_repo():
    return AsyncMock()


@pytest.fixture
def user_repo():
    repo = AsyncMock()
    repo.get_by_id_in_company.return_value = _user(id="emp-2", username="emp2")
    return repo


@pytest.fixture
def policy():
    policy_mock = AsyncMock()
    policy_mock.evaluate.return_value = TransferPolicyDecision(
        permit=True, reason_code=None, message_tr=None, cross_unit=False
    )
    return policy_mock


@pytest.fixture
def conversation_service():
    service = AsyncMock()
    service.open_dm.return_value = ConversationModel(
        id="conv-1", company_id="company-1", kind="dm", dm_key="emp-1:emp-2", created_by="emp-1",
        is_archived=False,
    )
    service.post_artifact_message.return_value = ConversationMessageModel(
        id="msg-1", company_id="company-1", conversation_id="conv-1", sender_id="emp-1",
        kind="artifact", body="", artifact_transfer_id="transfer-1",
    )
    return service


@pytest.fixture
def pool_service():
    service = AsyncMock()
    service.file_transferred_document.return_value = type(
        "Item", (), {"id": "item-1"}
    )()
    return service


@pytest.fixture
def audit_service():
    return AsyncMock()


@pytest.fixture
def quota_service():
    return AsyncMock()


@pytest.fixture
def service(
    transfer_repo, draft_repo, document_repo, user_repo, policy, conversation_service, pool_service,
    audit_service, quota_service,
):
    return ArtifactTransferService(
        transfer_repository=transfer_repo,
        draft_repository=draft_repo,
        document_repository=document_repo,
        user_repository=user_repo,
        policy=policy,
        conversation_service=conversation_service,
        pool_service=pool_service,
        audit_service=audit_service,
        quota_service=quota_service,
    )


def _cmd(**overrides) -> TransferCommand:
    fields = dict(
        company_id="company-1", sender=_user(id="emp-1"), recipient_id="emp-2",
        artifact_kind="draft", source_artifact_id="draft-1", channel="chat",
    )
    fields.update(overrides)
    return TransferCommand(**fields)


@pytest.fixture(autouse=True)
def _no_real_event_publish(monkeypatch):
    published = AsyncMock()
    monkeypatch.setattr("app.domains.transfers.service.event_bus.publish", published)
    return published


# ---------- idempotency ----------


async def test_idempotency_key_short_circuits_to_the_existing_transfer(
    service, transfer_repo, draft_repo, policy
):
    existing = ArtifactTransferModel(id="transfer-0", company_id="company-1", artifact_kind="draft",
                                      source_artifact_id="draft-1", sender_id="emp-1", recipient_id="emp-2",
                                      channel="chat", status="executed", policy_decision="permit")
    transfer_repo.get_by_idempotency_key.return_value = existing

    result = await service.execute(_cmd(idempotency_key="intent:abc"))

    assert result is existing
    draft_repo.get_by_id.assert_not_awaited()
    policy.evaluate.assert_not_awaited()


# ---------- not found ----------


async def test_raises_not_found_when_draft_missing(service, draft_repo):
    draft_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundException):
        await service.execute(_cmd(artifact_kind="draft"))


async def test_raises_not_found_when_draft_belongs_to_another_company(service, draft_repo):
    draft_repo.get_by_id.return_value = _draft(company_id="company-2")
    with pytest.raises(NotFoundException):
        await service.execute(_cmd(artifact_kind="draft"))


async def test_raises_not_found_when_draft_is_soft_deleted(service, draft_repo):
    draft_repo.get_by_id.return_value = _draft(is_deleted=True)
    with pytest.raises(NotFoundException):
        await service.execute(_cmd(artifact_kind="draft"))


async def test_raises_not_found_when_document_missing(service, draft_repo, document_repo):
    draft_repo.get_by_id.return_value = _draft()
    document_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundException):
        await service.execute(_cmd(artifact_kind="document", source_artifact_id="uploads/doc.pdf"))


async def test_raises_not_found_when_recipient_missing(service, draft_repo, user_repo):
    draft_repo.get_by_id.return_value = _draft()
    user_repo.get_by_id_in_company.return_value = None
    with pytest.raises(NotFoundException):
        await service.execute(_cmd())


async def test_raises_validation_error_for_an_unknown_artifact_kind(service, draft_repo):
    draft_repo.get_by_id.return_value = _draft()
    with pytest.raises(ValidationException):
        await service.execute(_cmd(artifact_kind="banana"))


# ---------- authorization / policy ----------


async def test_denies_a_non_owner_employee(service, draft_repo):
    draft_repo.get_by_id.return_value = _draft(user_id="someone-else")
    with pytest.raises(AuthorizationException):
        await service.execute(_cmd(sender=_user(id="emp-1", role="employee")))


async def test_allows_an_admin_that_does_not_own_the_draft(service, draft_repo):
    draft_repo.get_by_id.return_value = _draft(user_id="someone-else")
    transfer = await service.execute(_cmd(sender=_user(id="admin-1", role="admin")))
    assert transfer is not None


async def test_denies_when_policy_denies(service, draft_repo, policy):
    draft_repo.get_by_id.return_value = _draft()
    policy.evaluate.return_value = TransferPolicyDecision(
        permit=False, reason_code="self_transfer", message_tr="Kendinize transfer yapamazsınız.", cross_unit=False
    )
    with pytest.raises(AuthorizationException):
        await service.execute(_cmd())


# ---------- draft snapshot ----------


async def test_draft_transfer_forks_a_new_version_owned_by_the_recipient(
    service, draft_repo, quota_service
):
    original = _draft(id="draft-1", user_id="emp-1", content="orijinal içerik", destination_unit_id="unit-a")
    draft_repo.get_by_id.return_value = original

    transfer = await service.execute(_cmd())

    draft_repo.create_version.assert_awaited_once()
    call_kwargs = draft_repo.create_version.await_args.kwargs
    assert call_kwargs["user_id"] == "emp-2"
    assert call_kwargs["parent"] is original
    assert call_kwargs["content"] == "orijinal içerik"
    assert call_kwargs["destination_unit_id"] == "unit-a"
    assert transfer.snapshot_ref == "draft-2"
    assert transfer.artifact_kind == "draft"
    quota_service.check_and_increment.assert_awaited_once()


async def test_draft_transfer_pins_the_source_version(service, draft_repo):
    draft_repo.get_by_id.return_value = _draft(version=5)
    transfer = await service.execute(_cmd())
    assert transfer.source_version == 5


# ---------- document snapshot ----------


async def test_document_transfer_files_via_pool_service_not_draft_repository(
    service, document_repo, draft_repo, pool_service
):
    document_repo.get_by_id.return_value = _document()
    transfer = await service.execute(
        _cmd(artifact_kind="document", source_artifact_id="uploads/doc.pdf")
    )
    pool_service.file_transferred_document.assert_awaited_once()
    draft_repo.create_version.assert_not_awaited()
    assert transfer.snapshot_ref == "item-1"
    assert transfer.artifact_kind == "document"
    assert transfer.source_version is None


async def test_document_transfer_does_not_touch_the_draft_quota(service, document_repo, quota_service):
    document_repo.get_by_id.return_value = _document()
    await service.execute(_cmd(artifact_kind="document", source_artifact_id="uploads/doc.pdf"))
    quota_service.check_and_increment.assert_not_awaited()


async def test_document_transfer_passes_resolved_sensitivity_to_policy(service, document_repo, policy):
    document_repo.get_by_id.return_value = _document(sensitivity_level="gizli")
    await service.execute(_cmd(artifact_kind="document", source_artifact_id="uploads/doc.pdf"))
    policy_kwargs = policy.evaluate.await_args.kwargs
    assert policy_kwargs["artifact_sensitivity"].value == "gizli"


async def test_draft_transfer_passes_no_sensitivity_to_policy(service, draft_repo, policy):
    draft_repo.get_by_id.return_value = _draft()
    await service.execute(_cmd())
    policy_kwargs = policy.evaluate.await_args.kwargs
    assert policy_kwargs["artifact_sensitivity"] is None


# ---------- delivery, audit, notification ----------


async def test_delivers_into_a_dm_and_posts_an_artifact_message(
    service, draft_repo, conversation_service
):
    draft_repo.get_by_id.return_value = _draft()
    transfer = await service.execute(_cmd())

    conversation_service.open_dm.assert_awaited_once()
    conversation_service.post_artifact_message.assert_awaited_once()
    assert transfer.conversation_id == "conv-1"
    assert transfer.message_id == "msg-1"


async def test_records_audit_after_a_successful_transfer(service, draft_repo, audit_service):
    draft_repo.get_by_id.return_value = _draft()
    await service.execute(_cmd())
    audit_service.record.assert_awaited_once()
    assert audit_service.record.await_args.kwargs["action"] == "artifact:transfer"


async def test_publishes_the_transferred_event(service, draft_repo, _no_real_event_publish):
    draft_repo.get_by_id.return_value = _draft()
    await service.execute(_cmd())
    _no_real_event_publish.assert_awaited_once()


async def test_persisted_transfer_carries_the_policy_s_cross_unit_flag(service, draft_repo, policy):
    draft_repo.get_by_id.return_value = _draft()
    policy.evaluate.return_value = TransferPolicyDecision(
        permit=True, reason_code=None, message_tr=None, cross_unit=True
    )
    transfer = await service.execute(_cmd())
    assert transfer.cross_unit is True


# ---------- Prometheus metrics (Faz 5, #205) ----------


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


async def test_a_successful_transfer_increments_the_success_counter(service, draft_repo):
    draft_repo.get_by_id.return_value = _draft()
    before = _counter_value(transfer_metrics.ARTIFACT_TRANSFERS, channel="chat", result="success")

    await service.execute(_cmd(channel="chat"))

    after = _counter_value(transfer_metrics.ARTIFACT_TRANSFERS, channel="chat", result="success")
    assert after == before + 1


async def test_a_policy_denial_increments_both_the_reason_and_the_denied_counters(
    service, draft_repo, policy
):
    draft_repo.get_by_id.return_value = _draft()
    policy.evaluate.return_value = TransferPolicyDecision(
        permit=False, reason_code="self_transfer", message_tr="Kendinize transfer yapamazsınız.", cross_unit=False
    )
    denials_before = _counter_value(transfer_metrics.TRANSFER_POLICY_DENIALS, reason="self_transfer")
    denied_before = _counter_value(transfer_metrics.ARTIFACT_TRANSFERS, channel="chat", result="denied")

    with pytest.raises(AuthorizationException):
        await service.execute(_cmd(channel="chat"))

    assert _counter_value(transfer_metrics.TRANSFER_POLICY_DENIALS, reason="self_transfer") == denials_before + 1
    assert _counter_value(transfer_metrics.ARTIFACT_TRANSFERS, channel="chat", result="denied") == denied_before + 1


async def test_a_pdp_denial_increments_the_denied_counter_but_not_a_policy_reason(service, draft_repo):
    draft_repo.get_by_id.return_value = _draft(user_id="someone-else")
    denied_before = _counter_value(transfer_metrics.ARTIFACT_TRANSFERS, channel="chat", result="denied")

    with pytest.raises(AuthorizationException):
        await service.execute(_cmd(sender=_user(id="emp-1", role="employee"), channel="chat"))

    assert _counter_value(transfer_metrics.ARTIFACT_TRANSFERS, channel="chat", result="denied") == denied_before + 1


async def test_a_missing_recipient_increments_the_not_found_counter(service, draft_repo, user_repo):
    draft_repo.get_by_id.return_value = _draft()
    user_repo.get_by_id_in_company.return_value = None
    not_found_before = _counter_value(transfer_metrics.ARTIFACT_TRANSFERS, channel="chat", result="not_found")

    with pytest.raises(NotFoundException):
        await service.execute(_cmd(channel="chat"))

    assert (
        _counter_value(transfer_metrics.ARTIFACT_TRANSFERS, channel="chat", result="not_found")
        == not_found_before + 1
    )


async def test_an_idempotent_replay_does_not_increment_any_counter(service, transfer_repo, draft_repo):
    existing = ArtifactTransferModel(id="transfer-0", company_id="company-1", artifact_kind="draft",
                                      source_artifact_id="draft-1", sender_id="emp-1", recipient_id="emp-2",
                                      channel="chat", status="executed", policy_decision="permit")
    transfer_repo.get_by_idempotency_key.return_value = existing
    before = _counter_value(transfer_metrics.ARTIFACT_TRANSFERS, channel="chat", result="success")

    await service.execute(_cmd(channel="chat", idempotency_key="intent:abc"))

    assert _counter_value(transfer_metrics.ARTIFACT_TRANSFERS, channel="chat", result="success") == before


# ---------- group transfer fan-out (Faz 5, #205) ----------


def _group_cmd(**overrides) -> GroupTransferCommand:
    fields = dict(
        company_id="company-1", sender=_user(id="emp-1"), recipient_ids=("emp-2", "emp-3"),
        artifact_kind="draft", source_artifact_id="draft-1",
    )
    fields.update(overrides)
    return GroupTransferCommand(**fields)


async def test_execute_group_raises_validation_error_for_an_empty_recipient_list(service):
    with pytest.raises(ValidationException):
        await service.execute_group(_group_cmd(recipient_ids=()))


async def test_execute_group_raises_validation_error_over_the_recipient_cap(service):
    too_many = tuple(f"user-{i}" for i in range(MAX_GROUP_TRANSFER_RECIPIENTS + 1))
    with pytest.raises(ValidationException):
        await service.execute_group(_group_cmd(recipient_ids=too_many))


async def test_execute_group_reports_every_recipient_as_sent_on_a_clean_run(
    service, draft_repo, user_repo
):
    draft_repo.get_by_id.return_value = _draft()
    user_repo.get_by_id_in_company.side_effect = lambda user_id, company_id: _user(id=user_id)

    results = await service.execute_group(_group_cmd())

    assert {r.recipient_id: r.status for r in results} == {"emp-2": "sent", "emp-3": "sent"}
    assert all(r.transfer_id for r in results)


async def test_execute_group_always_uses_the_chat_channel(service, draft_repo, user_repo, policy):
    """`GroupTransferCommand` has no `channel` field -- `execute_group` is
    the chat/REST-only fan-out; the AI channel never builds one of these
    (see `execute_group`'s own docstring)."""
    draft_repo.get_by_id.return_value = _draft()
    user_repo.get_by_id_in_company.side_effect = lambda user_id, company_id: _user(id=user_id)

    await service.execute_group(_group_cmd(recipient_ids=("emp-2",)))

    assert policy.evaluate.await_args.kwargs["channel"] == "chat"


async def test_execute_group_a_denial_for_one_recipient_does_not_block_the_others(
    service, draft_repo, user_repo, policy
):
    draft_repo.get_by_id.return_value = _draft()
    user_repo.get_by_id_in_company.side_effect = lambda user_id, company_id: _user(id=user_id)

    async def _evaluate(*, recipient, **kwargs):
        if recipient.id == "emp-2":
            return TransferPolicyDecision(
                permit=False, reason_code="recipient_inactive", message_tr="Alıcı artık aktif değil.",
                cross_unit=False,
            )
        return TransferPolicyDecision(permit=True, reason_code=None, message_tr=None, cross_unit=False)

    policy.evaluate.side_effect = _evaluate

    results = await service.execute_group(_group_cmd(recipient_ids=("emp-2", "emp-3")))

    by_recipient = {r.recipient_id: r for r in results}
    assert by_recipient["emp-2"].status == "denied"
    assert by_recipient["emp-2"].reason == "Alıcı artık aktif değil."
    assert by_recipient["emp-3"].status == "sent"
    assert by_recipient["emp-3"].transfer_id is not None


async def test_execute_group_reports_a_missing_recipient_as_not_found(service, draft_repo, user_repo):
    draft_repo.get_by_id.return_value = _draft()

    async def _lookup(user_id, company_id):
        return None if user_id == "emp-2" else _user(id=user_id)

    user_repo.get_by_id_in_company.side_effect = _lookup

    results = await service.execute_group(_group_cmd(recipient_ids=("emp-2", "emp-3")))

    by_recipient = {r.recipient_id: r for r in results}
    assert by_recipient["emp-2"].status == "not_found"
    assert by_recipient["emp-3"].status == "sent"


async def test_execute_group_derives_a_distinct_idempotency_key_per_recipient(
    service, draft_repo, user_repo, transfer_repo
):
    draft_repo.get_by_id.return_value = _draft()
    user_repo.get_by_id_in_company.side_effect = lambda user_id, company_id: _user(id=user_id)

    await service.execute_group(
        _group_cmd(recipient_ids=("emp-2", "emp-3"), idempotency_key_prefix="intent:xyz")
    )

    keys = [call.args[1] for call in transfer_repo.get_by_idempotency_key.await_args_list]
    assert keys == ["intent:xyz:emp-2", "intent:xyz:emp-3"]
