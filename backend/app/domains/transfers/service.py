"""The single path every artifact (taslak/evrak) transfer goes through.

`ArtifactTransferService.execute` is called by every channel that moves an
artifact from one user to another -- `DraftShareService.send` (the legacy
REST endpoint, now a thin delegate), `POST /transfers/send` (the new
chat-initiated manual send), and, from Faz 4 onward, the AI channel's
`transfer_execute` node. There is no second implementation anywhere; see
the plan's own architecture section for why this unification is the point
of the whole feature, not an incidental refactor.
"""

import logging
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.api.exceptions.validation import ValidationException
from app.core.authz.attributes import Action, Resource
from app.core.authz.dependency import subject_from_user
from app.core.authz.engine import authorize
from app.core.enums.sensitivity_level import SensitivityLevel
from app.domains.audit.service import AuditService
from app.domains.documents.model.document_model import DocumentModel
from app.domains.documents.repository import DocumentRepository
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.repository import DraftRepository
from app.domains.messaging.service import ConversationService
from app.domains.pools.service import PoolService
from app.domains.quotas.service import DRAFTS_METRIC, QuotaService
from app.domains.transfers.model.transfer_model import ArtifactTransferModel
from app.domains.transfers.policy import TransferPolicy
from app.domains.transfers.repository import ArtifactTransferRepository
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.events.event import ArtifactTransferredEvent
from app.events.event_bus import event_bus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransferCommand:
    """Everything `ArtifactTransferService.execute` needs, independent of
    which channel is calling it."""

    company_id: str
    sender: UserModel
    recipient_id: str
    #: "draft" | "document"
    artifact_kind: str
    source_artifact_id: str
    #: Pinned draft version -- ignored for a document. `None` is resolved
    #: to the artifact's own current version internally.
    source_version: Optional[int] = None
    #: "chat" | "ai" | "rest"
    channel: str = "chat"
    idempotency_key: Optional[str] = None
    #: Faz 4 only -- every channel this phase supports leaves these at
    #: their defaults.
    ai_suggested: bool = False
    recommendation_source: Optional[str] = None
    recommendation_confidence: Optional[float] = None


class ArtifactTransferService:
    def __init__(
        self,
        transfer_repository: ArtifactTransferRepository,
        draft_repository: DraftRepository,
        document_repository: DocumentRepository,
        user_repository: UserRepository,
        policy: TransferPolicy,
        conversation_service: ConversationService,
        pool_service: PoolService,
        audit_service: AuditService,
        quota_service: Optional[QuotaService] = None,
    ):
        self.transfer_repository = transfer_repository
        self.draft_repository = draft_repository
        self.document_repository = document_repository
        self.user_repository = user_repository
        self.policy = policy
        self.conversation_service = conversation_service
        self.pool_service = pool_service
        self.audit_service = audit_service
        self.quota_service = quota_service

    @staticmethod
    async def _publish(event) -> None:
        """Publish a domain event without letting listener failures break
        the request. Same pattern as `DraftShareService._publish`."""
        try:
            await event_bus.publish(event)
        except Exception:
            logger.exception("Failed to publish event %s", getattr(event, "event_type", "?"))

    async def execute(self, cmd: TransferCommand) -> ArtifactTransferModel:
        """Run one transfer end to end: idempotency -> authorize -> policy
        -> snapshot -> record -> deliver -> best-effort audit/notify.

        Raises:
            NotFoundException: The artifact or recipient doesn't resolve
                within `cmd.company_id`.
            AuthorizationException: The PDP denies `Action.ARTIFACT_
                TRANSFER`, or `TransferPolicy` denies for a narrower reason
                (self-send, inactive recipient, insufficient clearance, or
                -- AI channel only -- the recipient isn't a favorite).

        Returns:
            The persisted `ArtifactTransferModel`. When `cmd.idempotency_key`
            matches an existing transfer, that transfer is returned as-is
            and nothing new is created.
        """
        if cmd.idempotency_key:
            existing = await self.transfer_repository.get_by_idempotency_key(
                cmd.company_id, cmd.idempotency_key
            )
            if existing is not None:
                return existing

        if cmd.artifact_kind == "draft":
            draft = await self._load_draft(cmd.source_artifact_id, cmd.company_id)
            owner_id = draft.user_id
            sensitivity: Optional[SensitivityLevel] = None
            destination_unit_id = draft.destination_unit_id
        elif cmd.artifact_kind == "document":
            document = await self._load_document(cmd.source_artifact_id, cmd.company_id)
            owner_id = document.owner_id
            sensitivity = self._document_sensitivity(document)
            destination_unit_id = None
        else:
            raise ValidationException(message="Geçersiz artifact türü.")

        recipient = await self.user_repository.get_by_id_in_company(cmd.recipient_id, cmd.company_id)
        if recipient is None:
            raise NotFoundException(message="Kullanıcı bulunamadı.")

        resource = Resource(
            type=cmd.artifact_kind, id=cmd.source_artifact_id, company_id=cmd.company_id, owner_id=owner_id
        )
        decision = authorize(subject_from_user(cmd.sender), Action.ARTIFACT_TRANSFER, resource)
        if not decision.permit:
            raise AuthorizationException(message="Bu artifact'i gönderme izniniz yok.")

        policy_decision = await self.policy.evaluate(
            sender=cmd.sender,
            recipient=recipient,
            company_id=cmd.company_id,
            channel=cmd.channel,
            artifact_sensitivity=sensitivity,
            artifact_destination_unit_id=destination_unit_id,
        )
        if not policy_decision.permit:
            raise AuthorizationException(message=policy_decision.message_tr)

        if cmd.artifact_kind == "draft":
            snapshot_ref = await self._fork_draft(draft, recipient, cmd.company_id)
            source_version = cmd.source_version or draft.version
        else:
            snapshot_ref = await self._file_document(document, recipient, cmd.sender, cmd.company_id)
            source_version = None

        transfer = await self.transfer_repository.create(
            ArtifactTransferModel(
                id=uuid4().hex,
                company_id=cmd.company_id,
                artifact_kind=cmd.artifact_kind,
                source_artifact_id=cmd.source_artifact_id,
                source_version=source_version,
                snapshot_ref=snapshot_ref,
                sender_id=cmd.sender.id,
                recipient_id=recipient.id,
                channel=cmd.channel,
                ai_suggested=cmd.ai_suggested,
                recommendation_source=cmd.recommendation_source,
                recommendation_confidence=cmd.recommendation_confidence,
                cross_unit=policy_decision.cross_unit,
                confirmed_by_user=True,
                policy_decision="permit",
                policy_reason=None,
                status="executed",
                idempotency_key=cmd.idempotency_key,
            )
        )

        conversation = await self.conversation_service.open_dm(cmd.company_id, cmd.sender, recipient.id)
        message = await self.conversation_service.post_artifact_message(
            conversation.id, cmd.company_id, cmd.sender, transfer.id
        )
        transfer.conversation_id = conversation.id
        transfer.message_id = message.id
        await self.transfer_repository.db.flush()

        await self.audit_service.record(
            company_id=cmd.company_id,
            actor_user_id=cmd.sender.id,
            actor_role=cmd.sender.role,
            action="artifact:transfer",
            resource_type=cmd.artifact_kind,
            resource_id=cmd.source_artifact_id,
            after={
                "transfer_id": transfer.id,
                "recipient_id": recipient.id,
                "channel": cmd.channel,
                "cross_unit": policy_decision.cross_unit,
            },
        )
        await self._publish(
            ArtifactTransferredEvent(
                payload={
                    "company_id": cmd.company_id,
                    "transfer_id": transfer.id,
                    "artifact_kind": cmd.artifact_kind,
                    "sender_id": cmd.sender.id,
                    "sender_username": cmd.sender.username,
                    "recipient_id": recipient.id,
                    "conversation_id": conversation.id,
                }
            )
        )
        return transfer

    async def _load_draft(self, draft_id: str, company_id: str) -> DraftModel:
        draft = await self.draft_repository.get_by_id(draft_id)
        if draft is None or draft.is_deleted or draft.company_id != company_id:
            raise NotFoundException(message="Taslak bulunamadı.")
        return draft

    async def _load_document(self, storage_path: str, company_id: str) -> DocumentModel:
        document = await self.document_repository.get_by_id(storage_path, company_id)
        if document is None:
            raise NotFoundException(message="Evrak bulunamadı.")
        return document

    @staticmethod
    def _document_sensitivity(document: DocumentModel) -> SensitivityLevel:
        try:
            return SensitivityLevel(document.sensitivity_level)
        except ValueError:
            return SensitivityLevel.UNMARKED

    async def _fork_draft(self, draft: DraftModel, recipient: UserModel, company_id: str) -> str:
        """The recipient's own, immediately-owned copy -- see the plan's
        §D5: a `drafts` row is already an immutable version, so "snapshot"
        means forking one, the same mechanism `create_version` already
        gives every other revision. Counts against the recipient's own
        draft quota, same as any other new draft."""
        if self.quota_service is not None:
            await self.quota_service.check_and_increment(company_id, DRAFTS_METRIC)
        forked = await self.draft_repository.create_version(
            user_id=recipient.id,
            company_id=company_id,
            session_id=None,
            document_id=draft.document_id,
            content=draft.content,
            parent=draft,
            correspondence_type=draft.correspondence_type,
            destination=draft.destination,
            destination_unit_id=draft.destination_unit_id,
            destination_justification=draft.destination_justification,
        )
        return forked.id

    async def _file_document(
        self, document: DocumentModel, recipient: UserModel, sender: UserModel, company_id: str
    ) -> str:
        item = await self.pool_service.file_transferred_document(
            document=document, recipient=recipient, sender=sender, company_id=company_id
        )
        return item.id
