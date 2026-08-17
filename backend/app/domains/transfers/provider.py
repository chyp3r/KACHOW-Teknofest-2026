"""Builds a fully-wired `ArtifactTransferService` for a request-scoped session.

Shared by every router that needs to call `ArtifactTransferService.execute`
-- `transfers/router.py` itself and `drafts/router.py` (`DraftShareService.
send` delegates to it) -- so the dependency graph (policy, messaging,
pools, audit, quotas) is assembled in exactly one place rather than
duplicated per call site.
"""

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
from app.domains.transfers.policy import TransferPolicy
from app.domains.transfers.repository import ArtifactTransferRepository
from app.domains.transfers.service import ArtifactTransferService
from app.domains.units.repository import UnitMembershipRepository
from app.domains.users.repository import UserFavoriteRepository, UserRepository


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
