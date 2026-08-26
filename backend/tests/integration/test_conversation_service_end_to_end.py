"""End-to-end `ConversationService` behavior against a real, migrated Postgres.

`two_companies` gives one user per company -- not enough for a DM, which
needs two distinct users in the *same* company. This file adds a second
user to company A directly (owner connection, same raw-SQL style
`two_companies` itself uses) and drives everything else through the real
service + repositories, no mocks.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.exceptions.authorization import AuthorizationException

# Constructing the messaging models requires their foreign-key targets to
# already be registered in Base.metadata -- same reasoning
# `test_tenant_repository_scoping.py` documents for UnitModel/companies.
from app.domains.companies.model.company_model import CompanyModel  # noqa: F401
from app.domains.messaging.repository import (
    ConversationMessageRepository,
    ConversationParticipantRepository,
    ConversationRepository,
)
from app.domains.messaging.service import ConversationService
from app.domains.transfers.model.transfer_model import ArtifactTransferModel  # noqa: F401
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def owner_session_maker(owner_engine):
    return async_sessionmaker(bind=owner_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def second_user_in_company_a(owner_session_maker, two_companies) -> str:
    """Insert a second employee into company A's own company, return its id."""
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
                "username": f"conv-test-{uuid4().hex[:8]}",
                "email": f"conv-test-{uuid4().hex[:8]}@kachow.example",
            },
        )
        await session.commit()
    return user_id


def _service(session: AsyncSession) -> ConversationService:
    return ConversationService(
        ConversationRepository(session),
        ConversationParticipantRepository(session),
        ConversationMessageRepository(session),
        UserRepository(session),
        cache=None,
    )


async def test_open_dm_twice_returns_the_same_conversation(
    owner_session_maker, two_companies, second_user_in_company_a
):
    company_id = two_companies["a"]["company_id"]
    requester = UserModel(id=two_companies["a"]["user_id"], company_id=company_id, role="employee")

    async with owner_session_maker() as session:
        first = await _service(session).open_dm(company_id, requester, second_user_in_company_a)
        await session.commit()

    async with owner_session_maker() as session:
        second = await _service(session).open_dm(company_id, requester, second_user_in_company_a)
        await session.commit()

    assert first.id == second.id


async def test_dm_message_flows_and_unread_count_updates(
    owner_session_maker, two_companies, second_user_in_company_a
):
    company_id = two_companies["a"]["company_id"]
    sender = UserModel(id=two_companies["a"]["user_id"], company_id=company_id, role="employee", username="a")
    recipient = UserModel(id=second_user_in_company_a, company_id=company_id, role="employee", username="b")

    async with owner_session_maker() as session:
        conversation = await _service(session).open_dm(company_id, sender, recipient.id)
        await session.commit()

    async with owner_session_maker() as session:
        await _service(session).send_text_message(conversation.id, company_id, sender, "merhaba")
        await session.commit()

    async with owner_session_maker() as session:
        message_repo = ConversationMessageRepository(session)
        recipient_unread = await message_repo.count_unread(
            conversation.id, company_id, recipient.id, last_read_message_id=None
        )
        sender_unread = await message_repo.count_unread(
            conversation.id, company_id, sender.id, last_read_message_id=None
        )
    assert recipient_unread == 1
    assert sender_unread == 0

    async with owner_session_maker() as session:
        service = _service(session)
        participant = await service.mark_read(conversation.id, company_id, recipient, message_id=None)
        await session.commit()

    async with owner_session_maker() as session:
        message_repo = ConversationMessageRepository(session)
        unread_after = await message_repo.count_unread(
            conversation.id,
            company_id,
            recipient.id,
            last_read_message_id=participant.last_read_message_id,
        )
    assert unread_after == 0


async def test_a_left_group_member_cannot_send_but_can_still_read(
    owner_session_maker, two_companies, second_user_in_company_a
):
    company_id = two_companies["a"]["company_id"]
    owner_user = UserModel(id=two_companies["a"]["user_id"], company_id=company_id, role="employee")
    member = UserModel(id=second_user_in_company_a, company_id=company_id, role="employee")

    async with owner_session_maker() as session:
        conversation = await _service(session).create_group(company_id, owner_user, "Proje", [member.id])
        await session.commit()

    async with owner_session_maker() as session:
        await _service(session).send_text_message(conversation.id, company_id, owner_user, "ilk mesaj")
        await session.commit()

    async with owner_session_maker() as session:
        await _service(session).remove_participant(conversation.id, company_id, member, member.id)
        await session.commit()

    async with owner_session_maker() as session:
        service = _service(session)
        # Still readable -- a former participant keeps history access.
        messages = await service.list_messages(conversation.id, company_id, member)
        assert len(messages) == 1

        with pytest.raises(AuthorizationException):
            await service.send_text_message(conversation.id, company_id, member, "artık gönderemem")
