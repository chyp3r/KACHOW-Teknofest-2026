from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.domains.transfers.intent_service import (
    STATE_AMBIGUOUS,
    STATE_AWAITING_CONFIRMATION,
    STATE_CANCELLED,
    STATE_CONFIRMED,
    STATE_FAILED,
    STATE_POLICY_DENIED,
    STATE_TRANSFER_EXECUTED,
    STATE_UNRESOLVED,
    TransferIntentError,
    TransferIntentService,
)
from app.domains.transfers.model.transfer_intent_model import ArtifactTransferIntentModel
from app.domains.transfers.policy import TransferPolicyDecision
from app.domains.users.model.user_model import UserModel


def _user(**overrides) -> UserModel:
    fields = dict(
        id="emp-1", company_id="company-1", username="emp1", email="emp1@example.com",
        role="employee", clearance_level="hizmete_ozel", is_active=True, is_deleted=False,
        hashed_password="x", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return UserModel(**fields)


class FakeIntentRepository:
    """A real (in-memory) CAS, not a mock -- the state machine's correctness
    depends on the conditional-update semantics themselves, which an
    unconditional AsyncMock can't exercise."""

    def __init__(self):
        self.rows: dict[str, ArtifactTransferIntentModel] = {}

    async def create(self, intent: ArtifactTransferIntentModel) -> ArtifactTransferIntentModel:
        self.rows[intent.id] = intent
        return intent

    async def get_by_id(self, intent_id, company_id):
        row = self.rows.get(intent_id)
        if row is None or row.company_id != company_id:
            return None
        return row

    async def cas_update(self, intent_id, company_id, expected_states, **values):
        row = self.rows.get(intent_id)
        if row is None or row.company_id != company_id or row.state not in expected_states:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        return row


@pytest.fixture
def intent_repo():
    return FakeIntentRepository()


@pytest.fixture
def user_repo():
    repo = AsyncMock()
    repo.get_by_id_in_company.return_value = _user(id="emp-2", username="recipient")
    return repo


@pytest.fixture
def draft_repo():
    repo = AsyncMock()
    repo.get_by_id.return_value = None
    return repo


@pytest.fixture
def document_repo():
    return AsyncMock()


@pytest.fixture
def policy():
    pol = AsyncMock()
    pol.evaluate.return_value = TransferPolicyDecision(
        permit=True, reason_code=None, message_tr=None, cross_unit=False
    )
    return pol


@pytest.fixture
def transfer_service():
    svc = AsyncMock()
    svc.execute.return_value = type("Transfer", (), {"id": "transfer-1"})()
    return svc


@pytest.fixture
def service(intent_repo, user_repo, draft_repo, document_repo, policy, transfer_service):
    return TransferIntentService(
        intent_repository=intent_repo,
        user_repository=user_repo,
        draft_repository=draft_repo,
        document_repository=document_repo,
        policy=policy,
        transfer_service=transfer_service,
    )


@pytest.fixture
def requester():
    return _user(id="emp-1")


@pytest.mark.asyncio
async def test_open_with_resolved_recipient_and_permit_awaits_confirmation(service, requester):
    intent = await service.open(
        company_id="company-1", thread_id="t-1", run_id="r-1", requester=requester,
        artifact_kind="draft", source_artifact_id="draft-1", resolved_recipient_id="emp-2",
    )
    assert intent.state == STATE_AWAITING_CONFIRMATION
    assert intent.policy_hash is not None


@pytest.mark.asyncio
async def test_open_with_resolved_recipient_and_deny_is_policy_denied(service, policy, requester):
    policy.evaluate.return_value = TransferPolicyDecision(
        permit=False, reason_code="favorite_required", message_tr="Önce favorilerinize ekleyin.", cross_unit=False
    )
    intent = await service.open(
        company_id="company-1", thread_id="t-1", run_id="r-1", requester=requester,
        artifact_kind="draft", source_artifact_id="draft-1", resolved_recipient_id="emp-2",
    )
    assert intent.state == STATE_POLICY_DENIED
    assert intent.policy_snapshot["reason_code"] == "favorite_required"


@pytest.mark.asyncio
async def test_open_with_only_candidates_is_ambiguous_and_skips_policy(service, policy, requester):
    intent = await service.open(
        company_id="company-1", thread_id="t-1", run_id="r-1", requester=requester,
        artifact_kind="draft", source_artifact_id="draft-1",
        candidate_recipients=({"user_id": "emp-2"}, {"user_id": "emp-3"}),
    )
    assert intent.state == STATE_AMBIGUOUS
    policy.evaluate.assert_not_awaited()


@pytest.mark.asyncio
async def test_open_with_neither_is_unresolved(service, requester):
    intent = await service.open(
        company_id="company-1", thread_id="t-1", run_id="r-1", requester=requester,
        artifact_kind="draft", source_artifact_id="draft-1",
    )
    assert intent.state == STATE_UNRESOLVED


@pytest.mark.asyncio
async def test_select_recipient_moves_ambiguous_to_awaiting_confirmation(service, requester):
    intent = await service.open(
        company_id="company-1", thread_id="t-1", run_id="r-1", requester=requester,
        artifact_kind="draft", source_artifact_id="draft-1",
        candidate_recipients=({"user_id": "emp-2"}, {"user_id": "emp-3"}),
    )
    resolved = await service.select_recipient(
        intent_id=intent.id, company_id="company-1", recipient_id="emp-2", requester=requester
    )
    assert resolved.state == STATE_AWAITING_CONFIRMATION
    assert resolved.resolved_recipient_id == "emp-2"


@pytest.mark.asyncio
async def test_select_recipient_on_a_non_ambiguous_intent_raises_stale(service, requester):
    intent = await service.open(
        company_id="company-1", thread_id="t-1", run_id="r-1", requester=requester,
        artifact_kind="draft", source_artifact_id="draft-1", resolved_recipient_id="emp-2",
    )
    with pytest.raises(TransferIntentError) as exc:
        await service.select_recipient(
            intent_id=intent.id, company_id="company-1", recipient_id="emp-3", requester=requester
        )
    assert exc.value.reason == "stale"


@pytest.mark.asyncio
async def test_confirm_moves_awaiting_confirmation_to_confirmed(service, requester):
    intent = await service.open(
        company_id="company-1", thread_id="t-1", run_id="r-1", requester=requester,
        artifact_kind="draft", source_artifact_id="draft-1", resolved_recipient_id="emp-2",
    )
    confirmed = await service.confirm(intent_id=intent.id, company_id="company-1", requester=requester)
    assert confirmed.state == STATE_CONFIRMED


@pytest.mark.asyncio
async def test_confirm_on_a_non_awaiting_intent_raises_stale(service, requester):
    intent = await service.open(
        company_id="company-1", thread_id="t-1", run_id="r-1", requester=requester,
        artifact_kind="draft", source_artifact_id="draft-1",
    )  # UNRESOLVED
    with pytest.raises(TransferIntentError) as exc:
        await service.confirm(intent_id=intent.id, company_id="company-1", requester=requester)
    assert exc.value.reason == "stale"


@pytest.mark.asyncio
async def test_confirm_after_expiry_cancels_and_raises_expired(service, intent_repo, requester):
    intent = await service.open(
        company_id="company-1", thread_id="t-1", run_id="r-1", requester=requester,
        artifact_kind="draft", source_artifact_id="draft-1", resolved_recipient_id="emp-2",
    )
    intent_repo.rows[intent.id].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    with pytest.raises(TransferIntentError) as exc:
        await service.confirm(intent_id=intent.id, company_id="company-1", requester=requester)
    assert exc.value.reason == "expired"
    assert intent_repo.rows[intent.id].state == STATE_CANCELLED


@pytest.mark.asyncio
async def test_confirm_toctou_policy_change_denies_even_though_it_was_permitted_at_open(
    service, policy, intent_repo, requester
):
    """The TOCTOU guard the plan's §H calls for: something (a favorite
    removed, a clearance change) changes policy between the original check
    and confirmation -- confirm() must re-evaluate from scratch and refuse,
    never trust the snapshot taken at AWAITING_CONFIRMATION time."""
    intent = await service.open(
        company_id="company-1", thread_id="t-1", run_id="r-1", requester=requester,
        artifact_kind="draft", source_artifact_id="draft-1", resolved_recipient_id="emp-2",
    )
    assert intent.state == STATE_AWAITING_CONFIRMATION

    policy.evaluate.return_value = TransferPolicyDecision(
        permit=False, reason_code="favorite_required", message_tr="Favori kaldırıldı.", cross_unit=False
    )

    with pytest.raises(TransferIntentError) as exc:
        await service.confirm(intent_id=intent.id, company_id="company-1", requester=requester)
    assert exc.value.reason == "favorite_required"
    assert intent_repo.rows[intent.id].state == STATE_POLICY_DENIED


@pytest.mark.asyncio
async def test_execute_on_an_unconfirmed_intent_raises_not_confirmed(service, requester):
    """The server-enforced guarantee behind "onaysız execute yok": whatever
    the graph believes, execute() itself refuses anything not persisted as
    CONFIRMED."""
    intent = await service.open(
        company_id="company-1", thread_id="t-1", run_id="r-1", requester=requester,
        artifact_kind="draft", source_artifact_id="draft-1",
    )  # UNRESOLVED, never confirmed
    with pytest.raises(TransferIntentError) as exc:
        await service.execute(intent_id=intent.id, company_id="company-1", sender=requester)
    assert exc.value.reason == "not_confirmed"


@pytest.mark.asyncio
async def test_execute_on_a_confirmed_intent_delegates_and_settles_transfer_executed(
    service, transfer_service, intent_repo, requester
):
    intent = await service.open(
        company_id="company-1", thread_id="t-1", run_id="r-1", requester=requester,
        artifact_kind="draft", source_artifact_id="draft-1", resolved_recipient_id="emp-2",
    )
    await service.confirm(intent_id=intent.id, company_id="company-1", requester=requester)

    transfer = await service.execute(intent_id=intent.id, company_id="company-1", sender=requester)

    assert transfer.id == "transfer-1"
    call = transfer_service.execute.await_args.args[0]
    assert call.idempotency_key == f"intent:{intent.id}"
    assert call.channel == "ai"
    assert call.ai_suggested is True
    assert intent_repo.rows[intent.id].state == STATE_TRANSFER_EXECUTED
    assert intent_repo.rows[intent.id].resulting_transfer_id == "transfer-1"


@pytest.mark.asyncio
async def test_execute_failure_settles_failed_and_reraises(service, transfer_service, intent_repo, requester):
    intent = await service.open(
        company_id="company-1", thread_id="t-1", run_id="r-1", requester=requester,
        artifact_kind="draft", source_artifact_id="draft-1", resolved_recipient_id="emp-2",
    )
    await service.confirm(intent_id=intent.id, company_id="company-1", requester=requester)
    transfer_service.execute.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await service.execute(intent_id=intent.id, company_id="company-1", sender=requester)
    assert intent_repo.rows[intent.id].state == STATE_FAILED


@pytest.mark.asyncio
async def test_cancel_from_a_terminal_state_raises_stale(service, requester):
    intent = await service.open(
        company_id="company-1", thread_id="t-1", run_id="r-1", requester=requester,
        artifact_kind="draft", source_artifact_id="draft-1", resolved_recipient_id="emp-2",
    )
    await service.confirm(intent_id=intent.id, company_id="company-1", requester=requester)
    await service.execute(intent_id=intent.id, company_id="company-1", sender=requester)

    with pytest.raises(TransferIntentError) as exc:
        await service.cancel(intent_id=intent.id, company_id="company-1")
    assert exc.value.reason == "stale"


@pytest.mark.asyncio
async def test_recipient_not_found_at_policy_time_denies(service, user_repo, requester):
    user_repo.get_by_id_in_company.return_value = None
    intent = await service.open(
        company_id="company-1", thread_id="t-1", run_id="r-1", requester=requester,
        artifact_kind="draft", source_artifact_id="draft-1", resolved_recipient_id="ghost",
    )
    assert intent.state == STATE_POLICY_DENIED
    assert intent.policy_snapshot["reason_code"] == "recipient_not_found"
