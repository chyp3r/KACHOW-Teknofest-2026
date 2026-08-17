"""The AI channel's confirmation lifecycle -- a row-level CAS state machine
over `artifact_transfer_intents` (see `ArtifactTransferIntentModel`).

Plan §I:

    INTENT_DETECTED -> {AMBIGUOUS, RECIPIENT_RESOLVED, UNRESOLVED}
    RECIPIENT_RESOLVED -> {AWAITING_CONFIRMATION, POLICY_DENIED}
    AWAITING_CONFIRMATION -> {CONFIRMED, CANCELLED}   (interrupt() in transfer_gate_node)
    CONFIRMED -> {TRANSFER_EXECUTED, FAILED}

Every transition is a single `ArtifactTransferIntentRepository.cas_update`
call -- `UPDATE ... WHERE state IN (:expected)`. A duplicate confirmation (two
browser tabs, a replayed `interrupt()` resume) or a confirmation that arrives
after `expires_at` resolves to "0 rows changed", never a race: this is what
lets `planning_graph.transfer_gate_node`/`_step_transfer_execute` treat every
call here as safe to make more than once. `POLICY_CHECKED` from the plan's
diagram is not its own persisted state here -- computing the policy decision
and persisting its outcome (`AWAITING_CONFIRMATION`/`POLICY_DENIED`) happen
in the same call, so there is nothing a concurrent reader could observe
in between.

`confirm()` is the TOCTOU guard the plan's §H calls for: it re-evaluates
`TransferPolicy` from scratch (never trusts the snapshot taken when the
intent was first resolved) and compares the freshly computed `policy_hash`
against the one stored at `AWAITING_CONFIRMATION` time. A favorite removed,
a recipient deactivated, or a clearance change in between fails the
confirmation outright rather than silently trusting a stale decision.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from app.core.config import settings
from app.core.enums.sensitivity_level import SensitivityLevel
from app.domains.documents.repository import DocumentRepository
from app.domains.drafts.repository import DraftRepository
from app.domains.transfers.model.transfer_intent_model import ArtifactTransferIntentModel
from app.domains.transfers.model.transfer_model import ArtifactTransferModel
from app.domains.transfers.policy import TransferPolicy, TransferPolicyDecision
from app.domains.transfers.repository import ArtifactTransferIntentRepository
from app.domains.transfers.service import ArtifactTransferService, TransferCommand
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository

logger = logging.getLogger(__name__)

STATE_INTENT_DETECTED = "INTENT_DETECTED"
STATE_AMBIGUOUS = "AMBIGUOUS"
STATE_RECIPIENT_RESOLVED = "RECIPIENT_RESOLVED"
STATE_UNRESOLVED = "UNRESOLVED"
STATE_AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
STATE_POLICY_DENIED = "POLICY_DENIED"
STATE_CONFIRMED = "CONFIRMED"
STATE_CANCELLED = "CANCELLED"
STATE_TRANSFER_EXECUTED = "TRANSFER_EXECUTED"
STATE_FAILED = "FAILED"

#: States `cancel()` may still move out of -- every non-terminal state.
_CANCELLABLE_STATES = (
    STATE_INTENT_DETECTED,
    STATE_AMBIGUOUS,
    STATE_RECIPIENT_RESOLVED,
    STATE_AWAITING_CONFIRMATION,
)


class TransferIntentError(Exception):
    """Raised whenever a requested transition isn't the intent's to make
    right now -- a stale/duplicate confirmation, an expired intent, or a
    TOCTOU policy mismatch. `reason` is a machine tag (mirrors
    `TransferPolicyDecision.reason_code`); `message_tr` is ready to show.
    """

    def __init__(self, reason: str, message_tr: str):
        super().__init__(message_tr)
        self.reason = reason
        self.message_tr = message_tr


def _snapshot(decision: TransferPolicyDecision, recipient_id: str) -> dict:
    return {
        "permit": decision.permit,
        "reason_code": decision.reason_code,
        "cross_unit": decision.cross_unit,
        "recipient_id": recipient_id,
    }


def _hash_snapshot(snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TransferIntentService:
    def __init__(
        self,
        intent_repository: ArtifactTransferIntentRepository,
        user_repository: UserRepository,
        draft_repository: DraftRepository,
        document_repository: DocumentRepository,
        policy: TransferPolicy,
        transfer_service: ArtifactTransferService,
    ):
        self.intent_repository = intent_repository
        self.user_repository = user_repository
        self.draft_repository = draft_repository
        self.document_repository = document_repository
        self.policy = policy
        self.transfer_service = transfer_service

    async def open(
        self,
        *,
        company_id: str,
        thread_id: str,
        run_id: Optional[str],
        requester: UserModel,
        artifact_kind: str,
        source_artifact_id: str,
        source_version: Optional[int] = None,
        resolved_recipient_id: Optional[str] = None,
        candidate_recipients: tuple = (),
        ttl_seconds: Optional[int] = None,
    ) -> ArtifactTransferIntentModel:
        """Open a new intent from `transfer_resolve`'s resolution outcome.

        Exactly one of `resolved_recipient_id`/`candidate_recipients` should
        be populated -- a single confident recipient match moves straight to
        policy evaluation; more than one leaves the intent `AMBIGUOUS`,
        waiting on `select_recipient`; neither leaves it `UNRESOLVED`, a
        terminal state the caller reports to the user without ever pausing
        the graph on it.
        """
        ttl = ttl_seconds if ttl_seconds is not None else settings.TRANSFER_CONFIRMATION_TTL_SECONDS
        if resolved_recipient_id:
            initial_state = STATE_RECIPIENT_RESOLVED
        elif candidate_recipients:
            initial_state = STATE_AMBIGUOUS
        else:
            initial_state = STATE_UNRESOLVED

        intent = await self.intent_repository.create(
            ArtifactTransferIntentModel(
                id=uuid4().hex,
                company_id=company_id,
                thread_id=thread_id,
                run_id=run_id,
                requested_by=requester.id,
                artifact_kind=artifact_kind,
                source_artifact_id=source_artifact_id,
                source_version=source_version,
                resolved_recipient_id=resolved_recipient_id,
                candidate_recipients=list(candidate_recipients) or None,
                state=initial_state,
                cross_unit=False,
                expires_at=_utcnow() + timedelta(seconds=ttl),
            )
        )
        if initial_state == STATE_RECIPIENT_RESOLVED:
            intent = await self._evaluate_policy(intent, requester)
        return intent

    async def select_recipient(
        self, *, intent_id: str, company_id: str, recipient_id: str, requester: UserModel
    ) -> ArtifactTransferIntentModel:
        """Resolve a disambiguation answer -- the human picked, not the model."""
        intent = await self.intent_repository.cas_update(
            intent_id,
            company_id,
            (STATE_AMBIGUOUS,),
            resolved_recipient_id=recipient_id,
            state=STATE_RECIPIENT_RESOLVED,
        )
        if intent is None:
            raise TransferIntentError(
                "stale", "Bu seçim artık geçerli değil; işlemi yeniden başlatmanız gerekiyor."
            )
        return await self._evaluate_policy(intent, requester)

    async def confirm(
        self, *, intent_id: str, company_id: str, requester: UserModel
    ) -> ArtifactTransferIntentModel:
        """The TOCTOU-guarded transition to `CONFIRMED`.

        Re-runs `TransferPolicy.evaluate` from scratch rather than trusting
        `intent.policy_snapshot` -- the whole point of the hash comparison
        below is that nothing between `AWAITING_CONFIRMATION` and this call
        is assumed to still hold.
        """
        intent = await self.intent_repository.get_by_id(intent_id, company_id)
        if intent is None or intent.state != STATE_AWAITING_CONFIRMATION:
            raise TransferIntentError(
                "stale", "Bu onay isteği artık geçerli değil; işlem başka bir yerde sonuçlanmış olabilir."
            )
        if intent.expires_at is not None and intent.expires_at < _utcnow():
            await self.intent_repository.cas_update(
                intent.id, company_id, (STATE_AWAITING_CONFIRMATION,), state=STATE_CANCELLED
            )
            raise TransferIntentError(
                "expired", "Onay süresi doldu; işlemi yeniden başlatmanız gerekiyor."
            )

        decision, recipient = await self._compute_policy(intent, requester)
        if decision is None or not decision.permit:
            reason = "recipient_not_found" if decision is None else (decision.reason_code or "policy_denied")
            message = (
                "Alıcı artık uygun değil." if decision is None else (decision.message_tr or "Bu transfer artık onaylanamıyor.")
            )
            await self.intent_repository.cas_update(
                intent.id,
                company_id,
                (STATE_AWAITING_CONFIRMATION,),
                state=STATE_POLICY_DENIED,
                policy_snapshot={"reason_code": reason},
            )
            raise TransferIntentError(reason, message)

        snapshot = _snapshot(decision, recipient.id)
        new_hash = _hash_snapshot(snapshot)
        if intent.policy_hash and intent.policy_hash != new_hash:
            await self.intent_repository.cas_update(
                intent.id,
                company_id,
                (STATE_AWAITING_CONFIRMATION,),
                state=STATE_POLICY_DENIED,
                policy_snapshot=snapshot,
                policy_hash=new_hash,
            )
            raise TransferIntentError(
                "policy_changed",
                "Onaydan bu yana koşullar değişti (favori/yetki); işlem iptal edildi, lütfen tekrar deneyin.",
            )

        updated = await self.intent_repository.cas_update(
            intent.id, company_id, (STATE_AWAITING_CONFIRMATION,), state=STATE_CONFIRMED
        )
        if updated is None:
            raise TransferIntentError(
                "stale", "Bu onay isteği başka bir yerde zaten işlendi."
            )
        return updated

    async def cancel(
        self, *, intent_id: str, company_id: str
    ) -> ArtifactTransferIntentModel:
        updated = await self.intent_repository.cas_update(
            intent_id, company_id, _CANCELLABLE_STATES, state=STATE_CANCELLED
        )
        if updated is None:
            raise TransferIntentError("stale", "Bu işlem zaten sonuçlanmış.")
        return updated

    async def execute(
        self, *, intent_id: str, company_id: str, sender: UserModel
    ) -> ArtifactTransferModel:
        """Run the confirmed intent through `ArtifactTransferService`.

        Raises `TransferIntentError("not_confirmed", ...)` for any intent
        not currently `CONFIRMED` -- the graph's `_step_transfer_execute`
        must never reach this without a real, server-verified confirmation
        (see the plan's §H bypass-matrix: "Onaysız transfer -- imkânsız").
        """
        intent = await self.intent_repository.get_by_id(intent_id, company_id)
        if intent is None or intent.state != STATE_CONFIRMED:
            raise TransferIntentError(
                "not_confirmed", "Onaylanmamış bir transfer çalıştırılamaz."
            )

        try:
            transfer = await self.transfer_service.execute(
                TransferCommand(
                    company_id=company_id,
                    sender=sender,
                    recipient_id=intent.resolved_recipient_id,
                    artifact_kind=intent.artifact_kind,
                    source_artifact_id=intent.source_artifact_id,
                    source_version=intent.source_version,
                    channel="ai",
                    idempotency_key=f"intent:{intent.id}",
                    ai_suggested=True,
                )
            )
        except Exception:
            await self.intent_repository.cas_update(
                intent.id, company_id, (STATE_CONFIRMED,), state=STATE_FAILED
            )
            raise

        await self.intent_repository.cas_update(
            intent.id,
            company_id,
            (STATE_CONFIRMED,),
            state=STATE_TRANSFER_EXECUTED,
            resulting_transfer_id=transfer.id,
        )
        return transfer

    async def _compute_policy(
        self, intent: ArtifactTransferIntentModel, requester: UserModel
    ) -> tuple[Optional[TransferPolicyDecision], Optional[UserModel]]:
        recipient = await self.user_repository.get_by_id_in_company(
            intent.resolved_recipient_id, intent.company_id
        )
        if recipient is None:
            return None, None
        sensitivity, destination_unit_id = await self._artifact_policy_inputs(intent)
        decision = await self.policy.evaluate(
            sender=requester,
            recipient=recipient,
            company_id=intent.company_id,
            channel="ai",
            artifact_sensitivity=sensitivity,
            artifact_destination_unit_id=destination_unit_id,
        )
        return decision, recipient

    async def _evaluate_policy(
        self, intent: ArtifactTransferIntentModel, requester: UserModel
    ) -> ArtifactTransferIntentModel:
        decision, recipient = await self._compute_policy(intent, requester)
        if decision is None:
            updated = await self.intent_repository.cas_update(
                intent.id,
                intent.company_id,
                (STATE_RECIPIENT_RESOLVED,),
                state=STATE_POLICY_DENIED,
                policy_snapshot={"reason_code": "recipient_not_found"},
            )
            return updated or intent

        snapshot = _snapshot(decision, recipient.id)
        next_state = STATE_AWAITING_CONFIRMATION if decision.permit else STATE_POLICY_DENIED
        updated = await self.intent_repository.cas_update(
            intent.id,
            intent.company_id,
            (STATE_RECIPIENT_RESOLVED,),
            state=next_state,
            policy_snapshot=snapshot,
            policy_hash=_hash_snapshot(snapshot),
            cross_unit=decision.cross_unit,
        )
        return updated or intent

    async def _artifact_policy_inputs(
        self, intent: ArtifactTransferIntentModel
    ) -> tuple[Optional[SensitivityLevel], Optional[str]]:
        if intent.artifact_kind == "draft":
            draft = await self.draft_repository.get_by_id(intent.source_artifact_id)
            if draft is None or draft.company_id != intent.company_id:
                return None, None
            return None, draft.destination_unit_id
        document = await self.document_repository.get_by_id(intent.source_artifact_id, intent.company_id)
        if document is None:
            return None, None
        try:
            return SensitivityLevel(document.sensitivity_level), None
        except ValueError:
            return SensitivityLevel.UNMARKED, None
