import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import uuid4

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.core.permissions.role_checker import bypasses_ownership
from app.domains.messaging.model.conversation_message_model import ConversationMessageModel
from app.domains.messaging.model.conversation_model import ConversationModel
from app.domains.messaging.model.conversation_participant_model import ConversationParticipantModel
from app.domains.messaging.repository import (
    ConversationMessageRepository,
    ConversationParticipantRepository,
    ConversationRepository,
)
from app.domains.messaging.schema.message_schema import MessageResponse
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.events.event import ConversationMessageCreatedEvent
from app.events.event_bus import event_bus
from app.infrastructure.cache.redis import RedisCache

logger = logging.getLogger(__name__)

#: Group size ceiling -- a fan-out over the whole membership happens on
#: every message send (one event/live-push per active recipient, see
#: `ConversationMessageCreatedEvent`'s docstring) and on every participant
#: listing; unbounded growth would turn both into an O(N) cost paid on
#: every single message. Not enforced for a DM (always exactly 2 rows).
MAX_GROUP_PARTICIPANTS = 50


def messaging_channel_for(company_id: str, user_id: str) -> str:
    """The Redis pub/sub channel one user's live message stream listens on.

    Distinct prefix from `app.domains.notifications.service.channel_for`
    ("messaging:" vs "notifications:") -- a message push carries the full
    `MessageResponse` payload for an open thread to render immediately,
    while a notification push is a short unread-badge signal; conflating
    the two channels would make the notification stream noisy with content
    it has no use for.
    """
    return f"messaging:{company_id}:{user_id}"


def _dm_key(user_a: str, user_b: str) -> str:
    return ":".join(sorted((user_a, user_b)))


class ConversationService:
    """Service for `conversations`/`conversation_participants`/
    `conversation_messages` -- DM + group messaging.

    Access to a conversation is never an ABAC decision: a
    `ConversationParticipantModel` row is the grant itself (see that
    model's own docstring, and `DraftShareService`'s for the same pattern
    already established for `draft_shares`). Group *management* (rename,
    add/remove someone else) is gated the same way `PoolService`/
    `DraftShareService` gate their own polymorphic resources: the
    conversation's own `owner`, or ADMIN/MANAGER/ROOT company-wide via
    `bypasses_ownership` -- no new ABAC action was introduced for this,
    deliberately, since the row-is-the-grant pattern already covers it.
    """

    def __init__(
        self,
        conversation_repository: ConversationRepository,
        participant_repository: ConversationParticipantRepository,
        message_repository: ConversationMessageRepository,
        user_repository: UserRepository,
        cache: Optional[RedisCache] = None,
    ):
        self.conversation_repository = conversation_repository
        self.participant_repository = participant_repository
        self.message_repository = message_repository
        self.user_repository = user_repository
        self.cache = cache

    @staticmethod
    async def _publish(event) -> None:
        """Publish a domain event without letting listener failures break
        the request. Same pattern as `DraftShareService._publish`."""
        try:
            await event_bus.publish(event)
        except Exception:
            logger.exception("Failed to publish event %s", getattr(event, "event_type", "?"))

    # ---------- Conversations ----------

    async def open_dm(
        self, company_id: str, requester: UserModel, other_user_id: str
    ) -> ConversationModel:
        """Open (or resolve to) the DM between `requester` and `other_user_id`.

        Idempotent: a second call with the same pair returns the existing
        conversation (see `ConversationModel.dm_key`'s partial unique
        index) -- callers never need to check first, and a concurrent open
        from both sides at once still converges to one row (the loser of
        the unique-index race gets an IntegrityError, which the caller
        retries into `get_dm` finding what the winner just created).
        """
        if other_user_id == requester.id:
            raise AuthorizationException(message="Kendinizle bir konuşma başlatamazsınız.")

        other = await self.user_repository.get_by_id_in_company(other_user_id, company_id)
        if other is None:
            raise NotFoundException(message="Kullanıcı bulunamadı.")

        dm_key = _dm_key(requester.id, other_user_id)
        existing = await self.conversation_repository.get_dm(company_id, dm_key)
        if existing is not None:
            return existing

        conversation = await self.conversation_repository.create(
            ConversationModel(
                id=uuid4().hex,
                company_id=company_id,
                kind="dm",
                dm_key=dm_key,
                created_by=requester.id,
            )
        )
        await self.participant_repository.create_many(
            [
                ConversationParticipantModel(
                    id=uuid4().hex,
                    company_id=company_id,
                    conversation_id=conversation.id,
                    user_id=requester.id,
                    role_in_conversation="member",
                ),
                ConversationParticipantModel(
                    id=uuid4().hex,
                    company_id=company_id,
                    conversation_id=conversation.id,
                    user_id=other.id,
                    role_in_conversation="member",
                ),
            ]
        )
        return conversation

    async def create_group(
        self, company_id: str, requester: UserModel, title: str, participant_ids: List[str]
    ) -> ConversationModel:
        """Create a group conversation. `requester` becomes `owner`;
        `participant_ids` (deduplicated, self excluded) become `member`."""
        unique_ids = {uid for uid in participant_ids if uid != requester.id}
        if not unique_ids:
            raise AuthorizationException(message="Grup için kendinizden başka en az bir üye gerekli.")
        if len(unique_ids) + 1 > MAX_GROUP_PARTICIPANTS:
            raise AuthorizationException(
                message=f"Bir grup en fazla {MAX_GROUP_PARTICIPANTS} üye içerebilir."
            )

        members: List[UserModel] = []
        for user_id in unique_ids:
            member = await self.user_repository.get_by_id_in_company(user_id, company_id)
            if member is None:
                raise NotFoundException(message=f"Kullanıcı bulunamadı: {user_id}")
            members.append(member)

        conversation = await self.conversation_repository.create(
            ConversationModel(
                id=uuid4().hex,
                company_id=company_id,
                kind="group",
                title=title,
                created_by=requester.id,
            )
        )
        participants = [
            ConversationParticipantModel(
                id=uuid4().hex,
                company_id=company_id,
                conversation_id=conversation.id,
                user_id=requester.id,
                role_in_conversation="owner",
            )
        ] + [
            ConversationParticipantModel(
                id=uuid4().hex,
                company_id=company_id,
                conversation_id=conversation.id,
                user_id=member.id,
                role_in_conversation="member",
            )
            for member in members
        ]
        await self.participant_repository.create_many(participants)
        return conversation

    async def _get_participant_or_403(
        self, conversation_id: str, company_id: str, user_id: str
    ) -> ConversationParticipantModel:
        """The caller's own participant row, read-access variant -- a
        former (left) participant still passes this, since they keep read
        access to whatever history existed while they were in the
        conversation (see `ConversationParticipantModel.left_at`'s
        docstring). Write access needs an additional `left_at is None`
        check at the call site."""
        conversation = await self.conversation_repository.get_by_id(conversation_id, company_id)
        if conversation is None:
            raise NotFoundException(message="Konuşma bulunamadı.")
        participant = await self.participant_repository.get(conversation_id, user_id, company_id)
        if participant is None:
            raise AuthorizationException(message="Bu konuşmaya erişim izniniz yok.")
        return participant

    def _require_manage_rights(
        self,
        conversation: ConversationModel,
        participant: ConversationParticipantModel,
        requester: UserModel,
    ) -> None:
        """Group-management gate (rename/archive, add/remove *other*
        participants): the conversation's own `owner`, or ADMIN/MANAGER/
        ROOT company-wide (`bypasses_ownership`)."""
        if conversation.kind != "group":
            raise AuthorizationException(message="Bu işlem yalnızca grup konuşmaları için geçerli.")
        if participant.role_in_conversation == "owner" or bypasses_ownership(requester):
            return
        raise AuthorizationException(message="Bu işlem için grup sahibi olmanız gerekir.")

    async def get_conversation(
        self, conversation_id: str, company_id: str, requester: UserModel
    ) -> Tuple[ConversationModel, ConversationParticipantModel, List[ConversationParticipantModel]]:
        participant = await self._get_participant_or_403(conversation_id, company_id, requester.id)
        conversation = await self.conversation_repository.get_by_id(conversation_id, company_id)
        all_participants = await self.participant_repository.list_for_conversation(
            conversation_id, company_id
        )
        return conversation, participant, all_participants

    async def list_participants(
        self, conversation_id: str, company_id: str
    ) -> List[ConversationParticipantModel]:
        return await self.participant_repository.list_for_conversation(conversation_id, company_id)

    async def list_conversations(
        self, company_id: str, requester: UserModel, skip: int = 0, limit: int = 50
    ) -> Tuple[List[Tuple[ConversationModel, ConversationParticipantModel]], int]:
        items = await self.conversation_repository.list_for_user(
            company_id, requester.id, skip=skip, limit=limit
        )
        total = await self.conversation_repository.count_for_user(company_id, requester.id)
        return items, total

    async def update_conversation(
        self,
        conversation_id: str,
        company_id: str,
        requester: UserModel,
        title: Optional[str],
        is_archived: Optional[bool],
    ) -> ConversationModel:
        conversation, participant, _ = await self.get_conversation(conversation_id, company_id, requester)
        self._require_manage_rights(conversation, participant, requester)
        update_data = {}
        if title is not None:
            update_data["title"] = title
        if is_archived is not None:
            update_data["is_archived"] = is_archived
        return await self.conversation_repository.update(conversation, update_data)

    # ---------- Participants ----------

    async def add_participants(
        self, conversation_id: str, company_id: str, requester: UserModel, user_ids: List[str]
    ) -> List[ConversationParticipantModel]:
        conversation, participant, existing = await self.get_conversation(
            conversation_id, company_id, requester
        )
        self._require_manage_rights(conversation, participant, requester)

        existing_ids = {p.user_id for p in existing}
        to_add = [uid for uid in dict.fromkeys(user_ids) if uid not in existing_ids]
        if not to_add:
            return []
        if len(existing) + len(to_add) > MAX_GROUP_PARTICIPANTS:
            raise AuthorizationException(
                message=f"Bir grup en fazla {MAX_GROUP_PARTICIPANTS} üye içerebilir."
            )

        new_rows = []
        for user_id in to_add:
            member = await self.user_repository.get_by_id_in_company(user_id, company_id)
            if member is None:
                raise NotFoundException(message=f"Kullanıcı bulunamadı: {user_id}")
            new_rows.append(
                ConversationParticipantModel(
                    id=uuid4().hex,
                    company_id=company_id,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    role_in_conversation="member",
                )
            )
        return await self.participant_repository.create_many(new_rows)

    async def remove_participant(
        self, conversation_id: str, company_id: str, requester: UserModel, target_user_id: str
    ) -> None:
        """Self-leave: any participant may remove themselves at any time.
        Removing someone else requires group-management rights."""
        conversation, participant, _ = await self.get_conversation(conversation_id, company_id, requester)
        if conversation.kind != "group":
            raise AuthorizationException(message="Bire bir konuşmadan katılımcı çıkarılamaz.")

        if target_user_id == requester.id:
            target = participant
        else:
            self._require_manage_rights(conversation, participant, requester)
            target = await self.participant_repository.get(conversation_id, target_user_id, company_id)

        if target is None or target.left_at is not None:
            raise NotFoundException(message="Katılımcı bulunamadı.")
        await self.participant_repository.mark_left(target, datetime.now(timezone.utc))

    # ---------- Messages ----------

    async def send_text_message(
        self, conversation_id: str, company_id: str, sender: UserModel, body: str
    ) -> ConversationMessageModel:
        """Post a plain text message. Requires an *active* participant --
        a former (left) participant may still read history but not write
        (see `ConversationParticipantModel.left_at`'s docstring)."""
        participant = await self._get_participant_or_403(conversation_id, company_id, sender.id)
        if participant.left_at is not None:
            raise AuthorizationException(message="Bu konuşmadan ayrıldınız, mesaj gönderemezsiniz.")

        message = await self.message_repository.create(
            ConversationMessageModel(
                id=uuid4().hex,
                company_id=company_id,
                conversation_id=conversation_id,
                sender_id=sender.id,
                kind="text",
                body=body,
            )
        )
        conversation = await self.conversation_repository.get_by_id(conversation_id, company_id)
        await self.conversation_repository.touch_last_message(conversation, message.created_at)

        await self._notify_recipients(conversation_id, company_id, sender, message)
        return message

    async def _notify_recipients(
        self,
        conversation_id: str,
        company_id: str,
        sender: UserModel,
        message: ConversationMessageModel,
    ) -> None:
        """Live-push the new message and publish one
        `ConversationMessageCreatedEvent` per active recipient other than
        `sender` (see that event's own docstring for why one-per-recipient,
        not one-with-a-list)."""
        participants = await self.participant_repository.list_for_conversation(
            conversation_id, company_id, active_only=True
        )
        preview = message.body[:140]
        for recipient in participants:
            if recipient.user_id == sender.id:
                continue
            if self.cache is not None:
                payload = MessageResponse(
                    id=message.id,
                    conversation_id=message.conversation_id,
                    sender_id=message.sender_id,
                    sender_username=sender.username,
                    kind=message.kind,
                    body=message.body,
                    artifact_transfer_id=message.artifact_transfer_id,
                    created_at=message.created_at,
                ).model_dump_json()
                try:
                    await self.cache.publish(
                        messaging_channel_for(company_id, recipient.user_id), payload
                    )
                except Exception:
                    logger.exception("Failed to publish live message to %s", recipient.user_id)
            await self._publish(
                ConversationMessageCreatedEvent(
                    payload={
                        "company_id": company_id,
                        "conversation_id": conversation_id,
                        "message_id": message.id,
                        "sender_id": sender.id,
                        "sender_username": sender.username,
                        "recipient_id": recipient.user_id,
                        "kind": message.kind,
                        "body_preview": preview,
                    }
                )
            )

    async def list_messages(
        self,
        conversation_id: str,
        company_id: str,
        requester: UserModel,
        before_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[ConversationMessageModel]:
        await self._get_participant_or_403(conversation_id, company_id, requester.id)
        return await self.message_repository.list_for_conversation(
            conversation_id, company_id, before_id=before_id, limit=limit
        )

    async def mark_read(
        self, conversation_id: str, company_id: str, requester: UserModel, message_id: Optional[str]
    ) -> ConversationParticipantModel:
        participant = await self._get_participant_or_403(conversation_id, company_id, requester.id)
        target_id = message_id
        if target_id is None:
            newest = await self.message_repository.list_for_conversation(
                conversation_id, company_id, limit=1
            )
            if not newest:
                return participant
            target_id = newest[0].id
        return await self.participant_repository.mark_read(participant, target_id)
