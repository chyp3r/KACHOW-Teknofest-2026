"""End-to-end `ArtifactTransferService` behavior against a real, migrated
Postgres -- no mocks, the real repositories/services all the way through.

Same second-user-in-company-A trick `test_conversation_service_end_to_end.py`
already uses: `two_companies` gives one user per company, not enough for a
transfer, which needs a distinct sender and recipient in the same company.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domains.audit.repository import AuditLogRepository
from app.domains.audit.service import AuditService

# Constructing ArtifactTransferModel/ConversationModel (FK -> companies.id)
# requires CompanyModel to already be registered in Base.metadata -- same
# reasoning test_conversation_service_end_to_end.py documents.
from app.domains.companies.model.company_model import CompanyModel  # noqa: F401
from app.domains.documents.repository import DocumentRepository
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
from app.domains.transfers.service import ArtifactTransferService, TransferCommand
from app.domains.units.repository import UnitMembershipRepository
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserFavoriteRepository, UserRepository

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
                "username": f"transfer-test-{uuid4().hex[:8]}",
                "email": f"transfer-test-{uuid4().hex[:8]}@kachow.example",
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


async def test_draft_transfer_gives_the_recipient_their_own_independent_copy(
    owner_session_maker, two_companies, second_user_in_company_a
):
    company_id = two_companies["a"]["company_id"]
    sender = UserModel(id=two_companies["a"]["user_id"], company_id=company_id, role="employee", username="a")

    async with owner_session_maker() as session:
        transfer = await _service(session).execute(
            TransferCommand(
                company_id=company_id,
                sender=sender,
                recipient_id=second_user_in_company_a,
                artifact_kind="draft",
                source_artifact_id=two_companies["a"]["draft_id"],
                channel="chat",
            )
        )
        await session.commit()
        forked_id = transfer.snapshot_ref

    assert forked_id != two_companies["a"]["draft_id"]

    async with owner_session_maker() as session:
        draft_repo = DraftRepository(session)
        original = await draft_repo.get_by_id(two_companies["a"]["draft_id"])
        forked = await draft_repo.get_by_id(forked_id)

    assert forked.user_id == second_user_in_company_a
    assert forked.content == original.content
    assert forked.parent_draft_id == original.id
    # The sender's own original is untouched -- still owned by the sender.
    assert original.user_id == two_companies["a"]["user_id"]


async def test_sender_editing_the_document_afterward_never_changes_the_recipients_snapshot(
    owner_session_maker, two_companies, second_user_in_company_a
):
    company_id = two_companies["a"]["company_id"]
    sender = UserModel(id=two_companies["a"]["user_id"], company_id=company_id, role="employee", username="a")

    async with owner_session_maker() as session:
        transfer = await _service(session).execute(
            TransferCommand(
                company_id=company_id,
                sender=sender,
                recipient_id=second_user_in_company_a,
                artifact_kind="document",
                source_artifact_id=two_companies["a"]["document_id"],
                channel="chat",
            )
        )
        await session.commit()
        item_id = transfer.snapshot_ref

    async with owner_session_maker() as session:
        item = await DocumentPoolItemRepository(session).get_by_id(item_id, company_id)
        assert item.metadata_snapshot["summary"] == ""

    # The sender edits the original document's metadata after the transfer.
    async with owner_session_maker() as session:
        await session.execute(
            text("UPDATE documents SET summary = :summary WHERE id = :id"),
            {"summary": "Gönderim sonrası değişti", "id": two_companies["a"]["document_id"]},
        )
        await session.commit()

    async with owner_session_maker() as session:
        item = await DocumentPoolItemRepository(session).get_by_id(item_id, company_id)
        assert item.metadata_snapshot["summary"] == ""


async def test_idempotency_key_prevents_a_double_execute(
    owner_session_maker, two_companies, second_user_in_company_a
):
    company_id = two_companies["a"]["company_id"]
    sender = UserModel(id=two_companies["a"]["user_id"], company_id=company_id, role="employee", username="a")
    key = f"intent:{uuid4().hex}"

    async def _send():
        async with owner_session_maker() as session:
            transfer = await _service(session).execute(
                TransferCommand(
                    company_id=company_id,
                    sender=sender,
                    recipient_id=second_user_in_company_a,
                    artifact_kind="draft",
                    source_artifact_id=two_companies["a"]["draft_id"],
                    channel="chat",
                    idempotency_key=key,
                )
            )
            await session.commit()
            return transfer.id

    first_id = await _send()
    second_id = await _send()

    assert first_id == second_id

    async with owner_session_maker() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM artifact_transfers WHERE idempotency_key = :key"), {"key": key}
            )
        ).scalar_one()
    assert count == 1
