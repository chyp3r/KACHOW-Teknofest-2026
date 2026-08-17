"""Builds a fully-wired `ArtifactTransferService` for a request-scoped session.

Shared by every router that needs to call `ArtifactTransferService.execute`
-- `transfers/router.py` itself and `drafts/router.py` (`DraftShareService.
send` delegates to it) -- so the dependency graph (policy, messaging,
pools, audit, quotas) is assembled in exactly one place rather than
duplicated per call site.
"""

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit.repository import AuditLogRepository
from app.domains.audit.service import AuditService
from app.domains.documents.repository import DocumentRepository
from app.domains.drafts.repository import DraftRepository
from app.domains.messaging.repository import (
    ConversationMessageRepository,
    ConversationParticipantRepository,
    ConversationRepository,
)
from app.domains.messaging.service import ConversationService
from app.domains.pools.repository import DocumentPoolItemRepository, DocumentPoolRepository
from app.infrastructure.cache import get_cache
from app.domains.pools.service import PoolService
from app.domains.quotas.repository import CompanyQuotaRepository, UsageCounterRepository
from app.domains.quotas.service import QuotaService
from app.domains.transfers.artifact_resolution import ArtifactResolutionService
from app.domains.transfers.intent_service import TransferIntentError, TransferIntentService
from app.domains.transfers.model.transfer_intent_model import ArtifactTransferIntentModel
from app.domains.transfers.model.transfer_model import ArtifactTransferModel
from app.domains.transfers.policy import TransferPolicy
from app.domains.transfers.recipient_resolution import RecipientResolutionService
from app.domains.transfers.recommendation import RecipientRecommendationService
from app.domains.transfers.repository import ArtifactTransferIntentRepository, ArtifactTransferRepository
from app.domains.transfers.service import ArtifactTransferService
from app.domains.units.repository import UnitMembershipRepository, UnitRepository
from app.domains.users.repository import UserFavoriteRepository, UserRepository
from app.infrastructure.database.session import tenant_session


def build_transfer_service(db: AsyncSession) -> ArtifactTransferService:
    policy = TransferPolicy(
        unit_membership_repository=UnitMembershipRepository(db),
        favorite_repository=UserFavoriteRepository(db),
    )
    conversation_service = ConversationService(
        conversation_repository=ConversationRepository(db),
        participant_repository=ConversationParticipantRepository(db),
        message_repository=ConversationMessageRepository(db),
        user_repository=UserRepository(db),
        cache=get_cache(),
    )
    pool_service = PoolService(
        pool_repository=DocumentPoolRepository(db),
        item_repository=DocumentPoolItemRepository(db),
        document_repository=DocumentRepository(db),
        user_repository=UserRepository(db),
        unit_membership_repository=UnitMembershipRepository(db),
    )
    return ArtifactTransferService(
        transfer_repository=ArtifactTransferRepository(db),
        draft_repository=DraftRepository(db),
        document_repository=DocumentRepository(db),
        user_repository=UserRepository(db),
        policy=policy,
        conversation_service=conversation_service,
        pool_service=pool_service,
        audit_service=AuditService(AuditLogRepository(db)),
        quota_service=QuotaService(UsageCounterRepository(db), CompanyQuotaRepository(db)),
    )


def _build_intent_service(db: AsyncSession) -> TransferIntentService:
    """Wire a `TransferIntentService` sharing the same collaborators
    `build_transfer_service` already assembles -- `execute()` delegates to
    the exact same `ArtifactTransferService` every other channel uses."""
    policy = TransferPolicy(
        unit_membership_repository=UnitMembershipRepository(db),
        favorite_repository=UserFavoriteRepository(db),
    )
    return TransferIntentService(
        intent_repository=ArtifactTransferIntentRepository(db),
        user_repository=UserRepository(db),
        draft_repository=DraftRepository(db),
        document_repository=DocumentRepository(db),
        policy=policy,
        transfer_service=build_transfer_service(db),
    )


# ---------------------------------------------------------------------------
# Faz 4 -- the AI graph's transfer_provider. Every method below opens its own
# `tenant_session` and returns plain, already-detached data (dataclasses/
# dicts), never an ORM instance -- the same discipline
# `app.domains.units.provider.get_active_units_for_routing` documents for the
# same reason: the graph is compiled once per process, outside any
# request-scoped session, and an ORM object handed back after its session
# closed would raise on the next attribute access.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DraftCandidate:
    id: str
    correspondence_type: str
    version: int
    updated_at: str


@dataclass(frozen=True)
class DocumentCandidate:
    id: str
    file_name: str
    created_at: str


@dataclass(frozen=True)
class ArtifactResolutionSnapshot:
    """Plain-data mirror of `ArtifactResolution`, safe to carry in
    `PlanningState` (which must stay JSON-serialisable)."""

    status: str
    artifact_kind: str
    draft_candidates: tuple = ()
    document_candidates: tuple = ()


@dataclass(frozen=True)
class IntentSnapshot:
    """Plain-data mirror of `ArtifactTransferIntentModel`.

    `error_reason`/`error_message` are set instead of raising
    `TransferIntentError` across the provider boundary -- `app.ai.*` never
    imports `app.domains.*` (see `TransferGraphProvider`'s own docstring),
    so a domain-specific exception type cannot cross into
    `planning_graph.py`. Every provider method that could hit a stale/
    expired/TOCTOU-failed transition catches it here and reports it as
    plain data instead; a non-`None` `error_reason` is what the graph node
    checks, exactly the way it already checks `status == StepStatus.FAILED`
    for any other step.
    """

    id: str = ""
    state: str = ""
    artifact_kind: str = ""
    source_artifact_id: str = ""
    source_version: Optional[int] = None
    resolved_recipient_id: Optional[str] = None
    candidate_recipients: Optional[list] = None
    cross_unit: bool = False
    policy_snapshot: Optional[dict] = None
    expires_at: Optional[str] = None
    error_reason: Optional[str] = None
    error_message: Optional[str] = None


@dataclass(frozen=True)
class TransferOutcome:
    """Plain-data mirror of the `ArtifactTransferModel` `execute()` produces.

    See `IntentSnapshot`'s docstring for why errors are fields, not a raised
    exception.
    """

    id: str = ""
    status: str = ""
    artifact_kind: str = ""
    recipient_id: str = ""
    snapshot_ref: Optional[str] = None
    conversation_id: Optional[str] = None
    cross_unit: bool = False
    error_reason: Optional[str] = None
    error_message: Optional[str] = None


def _snapshot_intent(intent: ArtifactTransferIntentModel) -> IntentSnapshot:
    return IntentSnapshot(
        id=intent.id,
        state=intent.state,
        artifact_kind=intent.artifact_kind,
        source_artifact_id=intent.source_artifact_id,
        source_version=intent.source_version,
        resolved_recipient_id=intent.resolved_recipient_id,
        candidate_recipients=intent.candidate_recipients,
        cross_unit=intent.cross_unit,
        policy_snapshot=intent.policy_snapshot,
        expires_at=intent.expires_at.isoformat() if intent.expires_at else None,
    )


def _snapshot_transfer(transfer: ArtifactTransferModel) -> TransferOutcome:
    return TransferOutcome(
        id=transfer.id,
        status=transfer.status,
        artifact_kind=transfer.artifact_kind,
        recipient_id=transfer.recipient_id,
        snapshot_ref=transfer.snapshot_ref,
        conversation_id=transfer.conversation_id,
        cross_unit=transfer.cross_unit,
    )


class TransferGraphProvider:
    """Everything `planning_graph.py`'s `transfer_resolve`/`transfer_gate`/
    `transfer_execute` nodes need from the transfers domain, injected the
    same way `units_provider`/`adapter_provider` are (see
    `create_planning_graph`'s own docstring) -- `app.ai.*` never imports
    `app.domains.*` directly.
    """

    async def resolve_recipient(
        self, *, company_id: str, name: str, requester_id: str
    ) -> tuple:
        """Returns `(status, candidates)` -- `status` is
        `"resolved"|"ambiguous"|"not_found"`, `candidates` a tuple of
        `RecipientCandidate` (already a plain dataclass, safe as-is)."""
        async with tenant_session(company_id) as session:
            service = RecipientResolutionService(UserRepository(session), UserFavoriteRepository(session))
            resolution = await service.resolve(name=name, company_id=company_id, requester_id=requester_id)
            return resolution.status, resolution.candidates

    async def recommend_recipients(
        self, *, company_id: str, draft_id: str, requester_id: str, limit: int = 5
    ) -> tuple:
        async with tenant_session(company_id) as session:
            service = RecipientRecommendationService(
                draft_repository=DraftRepository(session),
                unit_repository=UnitRepository(session),
                unit_membership_repository=UnitMembershipRepository(session),
                favorite_repository=UserFavoriteRepository(session),
            )
            recommendations = await service.recommend_for_draft(draft_id, company_id, requester_id, limit)
            return tuple(recommendations)

    async def resolve_draft(
        self,
        *,
        company_id: str,
        user_id: str,
        thread_id: Optional[str],
        explicit_draft_id: Optional[str] = None,
    ) -> ArtifactResolutionSnapshot:
        async with tenant_session(company_id) as session:
            service = ArtifactResolutionService(DraftRepository(session), DocumentRepository(session))
            resolution = await service.resolve_draft(
                company_id=company_id,
                user_id=user_id,
                thread_id=thread_id,
                explicit_draft_id=explicit_draft_id,
            )
            candidates = tuple(
                DraftCandidate(
                    id=draft.id,
                    correspondence_type=draft.correspondence_type or "",
                    version=draft.version,
                    updated_at=draft.updated_at.isoformat() if draft.updated_at else "",
                )
                for draft in resolution.candidates
            )
            return ArtifactResolutionSnapshot(
                status=resolution.status, artifact_kind="draft", draft_candidates=candidates
            )

    async def resolve_document(
        self,
        *,
        company_id: str,
        user_id: str,
        explicit_document_id: Optional[str] = None,
        focus_document_id: Optional[str] = None,
    ) -> ArtifactResolutionSnapshot:
        async with tenant_session(company_id) as session:
            service = ArtifactResolutionService(DraftRepository(session), DocumentRepository(session))
            resolution = await service.resolve_document(
                company_id=company_id,
                user_id=user_id,
                explicit_document_id=explicit_document_id,
                focus_document_id=focus_document_id,
            )
            candidates = tuple(
                DocumentCandidate(
                    id=document.storage_path,
                    file_name=document.file_name,
                    created_at=document.created_at.isoformat() if document.created_at else "",
                )
                for document in resolution.candidates
            )
            return ArtifactResolutionSnapshot(
                status=resolution.status, artifact_kind="document", document_candidates=candidates
            )

    async def open_intent(
        self,
        *,
        company_id: str,
        thread_id: str,
        run_id: Optional[str],
        requester_id: str,
        artifact_kind: str,
        source_artifact_id: str,
        source_version: Optional[int] = None,
        resolved_recipient_id: Optional[str] = None,
        candidate_recipients: tuple = (),
    ) -> IntentSnapshot:
        async with tenant_session(company_id) as session:
            requester = await UserRepository(session).get_by_id_in_company(requester_id, company_id)
            if requester is None:
                return IntentSnapshot(
                    error_reason="requester_not_found", error_message="Kullanıcı bulunamadı."
                )
            service = _build_intent_service(session)
            intent = await service.open(
                company_id=company_id,
                thread_id=thread_id,
                run_id=run_id,
                requester=requester,
                artifact_kind=artifact_kind,
                source_artifact_id=source_artifact_id,
                source_version=source_version,
                resolved_recipient_id=resolved_recipient_id,
                candidate_recipients=candidate_recipients,
            )
            return _snapshot_intent(intent)

    async def select_recipient(
        self, *, company_id: str, intent_id: str, recipient_id: str, requester_id: str
    ) -> IntentSnapshot:
        async with tenant_session(company_id) as session:
            requester = await UserRepository(session).get_by_id_in_company(requester_id, company_id)
            if requester is None:
                return IntentSnapshot(
                    error_reason="requester_not_found", error_message="Kullanıcı bulunamadı."
                )
            service = _build_intent_service(session)
            try:
                intent = await service.select_recipient(
                    intent_id=intent_id, company_id=company_id, recipient_id=recipient_id, requester=requester
                )
            except TransferIntentError as exc:
                return IntentSnapshot(id=intent_id, error_reason=exc.reason, error_message=exc.message_tr)
            return _snapshot_intent(intent)

    async def confirm(self, *, company_id: str, intent_id: str, requester_id: str) -> IntentSnapshot:
        async with tenant_session(company_id) as session:
            requester = await UserRepository(session).get_by_id_in_company(requester_id, company_id)
            if requester is None:
                return IntentSnapshot(
                    error_reason="requester_not_found", error_message="Kullanıcı bulunamadı."
                )
            service = _build_intent_service(session)
            try:
                intent = await service.confirm(intent_id=intent_id, company_id=company_id, requester=requester)
            except TransferIntentError as exc:
                return IntentSnapshot(id=intent_id, error_reason=exc.reason, error_message=exc.message_tr)
            return _snapshot_intent(intent)

    async def cancel(self, *, company_id: str, intent_id: str) -> IntentSnapshot:
        async with tenant_session(company_id) as session:
            service = _build_intent_service(session)
            try:
                intent = await service.cancel(intent_id=intent_id, company_id=company_id)
            except TransferIntentError as exc:
                return IntentSnapshot(id=intent_id, error_reason=exc.reason, error_message=exc.message_tr)
            return _snapshot_intent(intent)

    async def execute(self, *, company_id: str, intent_id: str, sender_id: str) -> TransferOutcome:
        async with tenant_session(company_id) as session:
            sender = await UserRepository(session).get_by_id_in_company(sender_id, company_id)
            if sender is None:
                return TransferOutcome(
                    error_reason="requester_not_found", error_message="Kullanıcı bulunamadı."
                )
            service = _build_intent_service(session)
            try:
                transfer = await service.execute(intent_id=intent_id, company_id=company_id, sender=sender)
            except TransferIntentError as exc:
                return TransferOutcome(error_reason=exc.reason, error_message=exc.message_tr)
            return _snapshot_transfer(transfer)


def build_transfer_graph_provider() -> TransferGraphProvider:
    """Built once per process, like `PrototypeMatcher` -- stateless, every
    method opens its own session per call."""
    return TransferGraphProvider()
