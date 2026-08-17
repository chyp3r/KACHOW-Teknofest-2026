"""End-to-end tests for the Faz 5 (#205) hardening work -- group transfer
fan-out and document adoption -- against a real, migrated Postgres, the
same shape `test_transfer_end_to_end.py` already establishes for the base
transfer flow.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.exceptions.authorization import AuthorizationException

# Constructing ArtifactTransferModel/ConversationModel (FK -> companies.id)
# requires CompanyModel to already be registered in Base.metadata -- same
# reasoning test_conversation_service_end_to_end.py documents.
from app.core.config import settings
from app.domains.audit.repository import AuditLogRepository
from app.domains.audit.service import AuditService
from app.domains.companies.model.company_model import CompanyModel  # noqa: F401
from app.domains.documents.repository import DocumentRepository
from app.domains.documents.service import DocumentService
from app.domains.drafts.repository import DraftRepository
from app.domains.messaging.repository import (
    ConversationMessageRepository,
    ConversationParticipantRepository,
    ConversationRepository,
)
from app.domains.messaging.service import ConversationService
from app.domains.pools.repository import DocumentPoolItemRepository, DocumentPoolRepository
from app.domains.pools.service import PoolService
from app.domains.transfers.policy import TransferPolicy
from app.domains.transfers.repository import ArtifactTransferRepository
from app.domains.transfers.service import ArtifactTransferService, GroupTransferCommand, TransferCommand
from app.domains.units.repository import UnitMembershipRepository
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserFavoriteRepository, UserRepository
from app.infrastructure.storage.local import LocalStorage

pytestmark = pytest.mark.integration


@pytest.fixture
def owner_session_maker(owner_engine):
    return async_sessionmaker(bind=owner_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def second_user_in_company_a(owner_session_maker, two_companies) -> str:
    company_id = two_companies["a"]["company_id"]
    user_id = uuid4().hex
    async with owner_session_maker() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, company_id, username, email, hashed_password, role, "
                "clearance_level, is_active, is_deleted, created_at, updated_at) "
                "VALUES (:id, :cid, :username, :email, 'x', 'employee', 'hizmete_ozel', true, false, now(), now())"
            ),
            {
                "id": user_id,
                "cid": company_id,
                "username": f"transfer-hardening-{uuid4().hex[:8]}",
                "email": f"transfer-hardening-{uuid4().hex[:8]}@kachow.example",
            },
        )
        await session.commit()
    return user_id


def _service(session: AsyncSession) -> ArtifactTransferService:
    return ArtifactTransferService(
        transfer_repository=ArtifactTransferRepository(session),
        draft_repository=DraftRepository(session),
        document_repository=DocumentRepository(session),
        user_repository=UserRepository(session),
        policy=TransferPolicy(
            unit_membership_repository=UnitMembershipRepository(session),
            favorite_repository=UserFavoriteRepository(session),
        ),
        conversation_service=ConversationService(
            ConversationRepository(session),
            ConversationParticipantRepository(session),
            ConversationMessageRepository(session),
            UserRepository(session),
            cache=None,
        ),
        pool_service=PoolService(
            pool_repository=DocumentPoolRepository(session),
            item_repository=DocumentPoolItemRepository(session),
            document_repository=DocumentRepository(session),
            user_repository=UserRepository(session),
            unit_membership_repository=UnitMembershipRepository(session),
        ),
        audit_service=AuditService(AuditLogRepository(session)),
        quota_service=None,
    )


# ---------- group transfer fan-out ----------


async def test_group_transfer_a_denied_recipient_does_not_block_the_others(
    owner_session_maker, two_companies, second_user_in_company_a
):
    """Self-send (`recipient_id == sender.id`) is a real `TransferPolicy`
    denial (`reason_code="self_transfer"`) -- a convenient real-policy way
    to exercise "one bad recipient in the batch" without extra fixtures."""
    company_id = two_companies["a"]["company_id"]
    sender = UserModel(id=two_companies["a"]["user_id"], company_id=company_id, role="employee", username="a")

    async with owner_session_maker() as session:
        results = await _service(session).execute_group(
            GroupTransferCommand(
                company_id=company_id,
                sender=sender,
                recipient_ids=(second_user_in_company_a, sender.id),
                artifact_kind="draft",
                source_artifact_id=two_companies["a"]["draft_id"],
            )
        )
        await session.commit()

    by_recipient = {r.recipient_id: r for r in results}
    assert by_recipient[second_user_in_company_a].status == "sent"
    assert by_recipient[second_user_in_company_a].transfer_id is not None
    assert by_recipient[sender.id].status == "denied"
    assert by_recipient[sender.id].reason == "Kendinize transfer yapamazsınız."


# ---------- document adoption (copy-on-write) ----------


async def test_adopt_gives_the_recipient_their_own_owned_blob_and_document_row(
    owner_session_maker, two_companies, second_user_in_company_a
):
    company_id = two_companies["a"]["company_id"]
    sender_id = two_companies["a"]["user_id"]
    source_document_id = two_companies["a"]["document_id"]
    sender = UserModel(id=sender_id, company_id=company_id, role="employee", username="a")

    storage = LocalStorage(settings.LOCAL_STORAGE_DIR)
    await storage.put_file(source_document_id, b"%PDF-1.7 fake bytes")

    async with owner_session_maker() as session:
        transfer = await _service(session).execute(
            TransferCommand(
                company_id=company_id,
                sender=sender,
                recipient_id=second_user_in_company_a,
                artifact_kind="document",
                source_artifact_id=source_document_id,
                channel="chat",
            )
        )
        await session.commit()
        item_id = transfer.snapshot_ref

    async with owner_session_maker() as session:
        document_service = DocumentService(
            storage=storage,
            extractor=AsyncMock(),
            analysis_graph=MagicMock(),
            document_repository=DocumentRepository(session),
            pool_repository=DocumentPoolRepository(session),
            pool_item_repository=DocumentPoolItemRepository(session),
        )
        recipient = UserModel(
            id=second_user_in_company_a, company_id=company_id, role="employee", username="b"
        )
        adopted_item = await document_service.adopt_pool_item(
            item_id=item_id, current_user=recipient, company_id=company_id
        )
        await session.commit()
        new_document_id = adopted_item.document_id

    assert adopted_item.source == "adopted"
    assert new_document_id != source_document_id

    async with owner_session_maker() as session:
        new_document = await DocumentRepository(session).get_by_id(new_document_id, company_id)
        original_document = await DocumentRepository(session).get_by_id(source_document_id, company_id)

    assert new_document is not None
    assert new_document.owner_id == second_user_in_company_a
    # The sender's own original is untouched -- still owned by the sender,
    # still addressable under its own storage key.
    assert original_document.owner_id == sender_id

    # A real, independent blob -- not just a registry row pointing at the
    # same file.
    new_content = await storage.get_file(new_document_id)
    assert new_content == b"%PDF-1.7 fake bytes"
    original_content = await storage.get_file(source_document_id)
    assert original_content == b"%PDF-1.7 fake bytes"


async def test_adopt_requires_the_pool_item_s_own_owner(
    owner_session_maker, two_companies, second_user_in_company_a
):
    company_id = two_companies["a"]["company_id"]
    sender_id = two_companies["a"]["user_id"]
    source_document_id = two_companies["a"]["document_id"]
    sender = UserModel(id=sender_id, company_id=company_id, role="employee", username="a")

    storage = LocalStorage(settings.LOCAL_STORAGE_DIR)
    await storage.put_file(source_document_id, b"%PDF-1.7 fake bytes")

    async with owner_session_maker() as session:
        transfer = await _service(session).execute(
            TransferCommand(
                company_id=company_id,
                sender=sender,
                recipient_id=second_user_in_company_a,
                artifact_kind="document",
                source_artifact_id=source_document_id,
                channel="chat",
            )
        )
        await session.commit()
        item_id = transfer.snapshot_ref

    async with owner_session_maker() as session:
        document_service = DocumentService(
            storage=storage,
            extractor=AsyncMock(),
            analysis_graph=MagicMock(),
            document_repository=DocumentRepository(session),
            pool_repository=DocumentPoolRepository(session),
            pool_item_repository=DocumentPoolItemRepository(session),
        )
        # The sender (not the pool's own owner) tries to adopt the item
        # sitting in the recipient's personal pool.
        with pytest.raises(AuthorizationException):
            await document_service.adopt_pool_item(
                item_id=item_id, current_user=sender, company_id=company_id
            )
