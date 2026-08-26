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

#: Grup boyutu üst sınırı -- her mesaj gönderiminde tüm üyelik üzerinden
#: bir fan-out olur (her aktif alıcı için bir event/canlı-push, bkz.
#: `ConversationMessageCreatedEvent`'in docstring'i) ve her katılımcı
#: listelemesinde de aynısı olur; sınırsız büyüme her ikisini de her tek
#: mesajda ödenen bir O(N) maliyetine dönüştürür. DM için uygulanmaz
#: (her zaman tam olarak 2 satır).
MAX_GROUP_PARTICIPANTS = 50


def messaging_channel_for(company_id: str, user_id: str) -> str:
    """Bir kullanıcının canlı mesaj akışının dinlediği Redis pub/sub kanalı.

    `app.domains.notifications.service.channel_for`'dan farklı önek
    ("messaging:" vs "notifications:") -- bir mesaj push'u açık bir
    thread'in anında render edebilmesi için tam `MessageResponse`
    payload'ını taşır, oysa bir bildirim push'u kısa bir okunmamış-rozet
    sinyalidir; iki kanalı birleştirmek bildirim akışını hiç işine
    yaramayacak içerikle gürültülü hale getirirdi.
    """
    return f"messaging:{company_id}:{user_id}"


def _dm_key(user_a: str, user_b: str) -> str:
    return ":".join(sorted((user_a, user_b)))


class ConversationService:
    """`conversations`/`conversation_participants`/`conversation_messages`
    için servis -- DM + grup mesajlaşması.

    Bir konuşmaya erişim asla bir ABAC kararı değildir: bir
    `ConversationParticipantModel` satırı iznin kendisidir (bkz. o
    modelin kendi docstring'i, ve `draft_shares` için zaten kurulmuş aynı
    örüntü için `DraftShareService`'inki). Grup *yönetimi* (yeniden
    adlandırma, başkasını ekleme/çıkarma), `PoolService`/
    `DraftShareService`'in kendi polimorfik kaynaklarını kilitlediği
    şekilde kilitlenir: konuşmanın kendi `owner`'ı veya
    `bypasses_ownership` üzerinden şirket genelinde ADMIN/MANAGER/ROOT --
    bunun için yeni bir ABAC aksiyonu bilinçli olarak eklenmedi, çünkü
    satır-iznin-kendisidir örüntüsü bunu zaten kapsıyor.
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
        """Dinleyici hatalarının isteği bozmasına izin vermeden bir domain
        event'i yayınlar. `DraftShareService._publish` ile aynı örüntü."""
        try:
            await event_bus.publish(event)
        except Exception:
            logger.exception("Failed to publish event %s", getattr(event, "event_type", "?"))

    # ---------- Conversations ----------

    async def open_dm(
        self, company_id: str, requester: UserModel, other_user_id: str
    ) -> ConversationModel:
        """`requester` ile `other_user_id` arasındaki DM'i açar (veya
        mevcut olana çözümler).

        İdempotenttir: aynı çift ile ikinci bir çağrı mevcut konuşmayı
        döndürür (bkz. `ConversationModel.dm_key`'in kısmi unique
        index'i) -- çağıranların önce kontrol etmesine hiç gerek yoktur,
        ve iki taraftan aynı anda gelen eşzamanlı bir açma da yine tek
        bir satıra yakınsar (unique-index yarışının kaybedeni bir
        IntegrityError alır, çağıran bunu `get_dm`'e yeniden deneyerek
        kazananın az önce oluşturduğunu bulur).
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
        """Bir grup konuşması oluşturur. `requester` `owner` olur;
        `participant_ids` (tekrarları çıkarılmış, kendisi hariç) `member`
        olur."""
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
        """Çağıranın kendi katılımcı satırı, okuma-erişimi varyantı --
        eski (ayrılmış) bir katılımcı bunu yine de geçer, çünkü
        konuşmadayken var olan geçmişe okuma erişimini korur (bkz.
        `ConversationParticipantModel.left_at`'in docstring'i). Yazma
        erişimi çağrı noktasında ek bir `left_at is None` kontrolü
        gerektirir."""
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
        """Grup-yönetimi kapısı (yeniden adlandırma/arşivleme, *diğer*
        katılımcıları ekleme/çıkarma): konuşmanın kendi `owner`'ı veya
        şirket genelinde ADMIN/MANAGER/ROOT (`bypasses_ownership`)."""
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
        """Kendi kendine ayrılma: herhangi bir katılımcı her zaman
        kendisini çıkarabilir. Başkasını çıkarmak grup-yönetimi hakları
        gerektirir."""
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
        """Düz metin bir mesaj gönderir. *Aktif* bir katılımcı gerektirir
        -- eski (ayrılmış) bir katılımcı geçmişi okuyabilir ama yazamaz
        (bkz. `ConversationParticipantModel.left_at`'in docstring'i)."""
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

    async def post_artifact_message(
        self, conversation_id: str, company_id: str, sender: UserModel, artifact_transfer_id: str
    ) -> ConversationMessageModel:
        """Tamamlanmış bir transfer için `kind="artifact"` bildirimini
        gönderir.

        Yalnızca `app.domains.transfers.ArtifactTransferService`
        tarafından, transferin kendisi aynı transaction içinde zaten
        commit edildikten sonra çağrılır -- `conversation_id`'nin
        `sender`'ı zaten aktif bir katılımcı olarak barındırdığı
        varsayılır (transfer servisi bunu çağırmadan önce DM'i açar/
        yeniden kullanır). `body` bilinçli olarak boştur: bir artifact
        mesajının kart içeriği (başlık, sürüm, durum) burada asla cache'
        lenmez -- frontend bunu `artifact_transfer_id`'den canlı okur,
        nedeni için `ConversationMessageModel`'in kendi docstring'ine
        bakın.
        """
        message = await self.message_repository.create(
            ConversationMessageModel(
                id=uuid4().hex,
                company_id=company_id,
                conversation_id=conversation_id,
                sender_id=sender.id,
                kind="artifact",
                body="",
                artifact_transfer_id=artifact_transfer_id,
            )
        )
        conversation = await self.conversation_repository.get_by_id(conversation_id, company_id)
        await self.conversation_repository.touch_last_message(conversation, message.created_at)
        # Genel bir "yeni mesaj" bildirimi yok -- ArtifactTransferService
        # kendi, daha spesifik olanını yayınlıyor (burada neden
        # `publish_event=False` olduğu için `_notify_recipients`'ın kendi
        # docstring'ine bakın).
        await self._notify_recipients(conversation_id, company_id, sender, message, publish_event=False)
        return message

    async def _notify_recipients(
        self,
        conversation_id: str,
        company_id: str,
        sender: UserModel,
        message: ConversationMessageModel,
        *,
        publish_event: bool = True,
    ) -> None:
        """Yeni mesajı `sender` dışındaki her aktif alıcıya canlı olarak
        gönderir ve (`publish_event=False` olmadıkça) alıcı başına bir
        `ConversationMessageCreatedEvent` yayınlar (neden alıcı-başına-bir
        olduğu, tek-liste-ile-bir olmadığı için o event'in kendi
        docstring'ine bakın).

        `publish_event=False`, `post_artifact_message`'ın kendi
        durumudur: bir artifact transferi zaten `ArtifactTransferService`
        'den kendi, daha spesifik bildirimini alır (bkz. onun
        docstring'i) -- burada genel "yeni mesaj" event'ini de yayınlamak
        onu ikiye katlardı. Canlı SSE push'u her iki durumda da yine
        gerçekleşir, bu yüzden thread'in kendisi yine gerçek zamanlı
        güncellenir.
        """
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
            if publish_event:
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
