"""İstek kapsamlı bir oturum için tam bağlı bir `ArtifactTransferService` oluşturur.

`ArtifactTransferService.execute`'u çağırması gereken her router tarafından
paylaşılır -- `transfers/router.py`'nin kendisi ve `drafts/router.py`
(`DraftShareService.send` buna delege eder) -- böylece bağımlılık grafiği
(politika, mesajlaşma, havuzlar, denetim, kotalar) her çağrı noktasında
tekrarlanmak yerine tam olarak tek bir yerde bir araya getirilir.
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
    """`build_transfer_service`'in zaten bir araya getirdiği aynı işbirlikçileri
    paylaşan bir `TransferIntentService` bağlar -- `execute()`, diğer her
    kanalın kullandığı tam olarak aynı `ArtifactTransferService`'e delege
    eder."""
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
# Faz 4 -- AI grafiğinin transfer_provider'ı. Aşağıdaki her metot kendi
# `tenant_session`'ını açar ve asla bir ORM örneği değil, düz, zaten
# bağlantısı kesilmiş veri (dataclass/dict) döndürür -- aynı gerekçeyle
# `app.domains.units.provider.get_active_units_for_routing`'in belgelediği
# aynı disiplin: grafik, herhangi bir istek kapsamlı oturumun dışında,
# süreç başına bir kez derlenir ve oturumu kapandıktan sonra geri verilen
# bir ORM nesnesi sonraki özellik erişiminde hata fırlatır.
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
    """`ArtifactResolution`'ın düz veri yansıması, `PlanningState` içinde
    taşınması güvenli (JSON serileştirilebilir kalmak zorunda)."""

    status: str
    artifact_kind: str
    draft_candidates: tuple = ()
    document_candidates: tuple = ()


@dataclass(frozen=True)
class IntentSnapshot:
    """`ArtifactTransferIntentModel`'in düz veri yansıması.

    Provider sınırı boyunca `TransferIntentError` fırlatmak yerine
    `error_reason`/`error_message` ayarlanır -- `app.ai.*` asla
    `app.domains.*`'ı import etmez (bkz. `TransferGraphProvider`'ın kendi
    docstring'i), dolayısıyla alan (domain) özel bir istisna tipi
    `planning_graph.py`'ye geçemez. Eskimiş/süresi dolmuş/TOCTOU
    başarısızlığı olan bir geçişe rastlayabilecek her provider metodu
    bunu burada yakalar ve bunun yerine düz veri olarak rapor eder;
    graf düğümünün kontrol ettiği şey `None` olmayan bir `error_reason`'dır,
    tıpkı diğer her adım için zaten `status == StepStatus.FAILED`'i
    kontrol ettiği gibi.
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
    """`execute()`'un ürettiği `ArtifactTransferModel`'in düz veri yansıması.

    Hataların neden fırlatılan bir istisna değil de alan olduğu için
    `IntentSnapshot`'ın docstring'ine bakın.
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
    """`propose_transfer` aracının (`app.ai.tools.transfer_tools`) ve
    `planning_graph.py`'nin `transfer_gate`/`transfer_execute`'ının
    transfers alanından ihtiyaç duyduğu her şey, `units_provider`/
    `adapter_provider`'ın enjekte edildiği aynı şekilde enjekte edilir
    (bkz. `create_planning_graph`'ın kendi docstring'i) --
    `app.ai.*` asla `app.domains.*`'ı doğrudan import etmez.
    """

    async def resolve_recipient(
        self, *, company_id: str, name: str, requester_id: str
    ) -> tuple:
        """`(status, candidates)` döndürür -- `status`,
        `"resolved"|"ambiguous"|"not_found"`, `candidates` ise
        `RecipientCandidate`'lardan (zaten düz bir dataclass, olduğu gibi
        güvenli) oluşan bir tuple'dır."""
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
    """`PrototypeMatcher` gibi süreç başına bir kez oluşturulur -- durumsuz
    (stateless), her metot her çağrıda kendi oturumunu açar."""
    return TransferGraphProvider()
