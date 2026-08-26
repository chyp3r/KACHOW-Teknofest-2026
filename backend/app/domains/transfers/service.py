"""Her belge (taslak/evrak) transferinin geçtiği tek yol.

`ArtifactTransferService.execute`, bir belgeyi bir kullanıcıdan diğerine
taşıyan her kanal tarafından çağrılır -- `DraftShareService.send` (eski
REST uç noktası, artık ince bir delege), `POST /transfers/send` (yeni,
sohbetten başlatılan manuel gönderim) ve Faz 4'ten itibaren AI kanalının
`transfer_execute` düğümü. Hiçbir yerde ikinci bir uygulama yok; bu
birleştirmenin neden sıradan bir refactor değil de tüm özelliğin amacı
olduğu için planın kendi mimari bölümüne bakın.
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
from app.observability import transfer_metrics

logger = logging.getLogger(__name__)

#: `GroupTransferCommand.recipient_ids` üzerindeki üst sınır --
#: `app.domains.messaging.service.MAX_GROUP_PARTICIPANTS` (grup sohbetinin
#: kendi tavanı) ile aynı büyüklük mertebesinde, bir transfer dağıtımı
#: belirli bir konuşmanın üyelik boyutuna bağlı olmadığından ayrı bir
#: sabit olarak tutulur.
MAX_GROUP_TRANSFER_RECIPIENTS = 50


@dataclass(frozen=True)
class TransferCommand:
    """Hangi kanalın çağırdığından bağımsız olarak `ArtifactTransferService.
    execute`'un ihtiyaç duyduğu her şey."""

    company_id: str
    sender: UserModel
    recipient_id: str
    #: "draft" | "document"
    artifact_kind: str
    source_artifact_id: str
    #: Sabitlenmiş taslak versiyonu -- bir evrak için yok sayılır. `None`,
    #: dahili olarak belgenin kendi güncel versiyonuna çözümlenir.
    source_version: Optional[int] = None
    #: "chat" | "ai" | "rest"
    channel: str = "chat"
    idempotency_key: Optional[str] = None
    #: Yalnızca Faz 4 -- bu fazın desteklediği her kanal bunları
    #: varsayılanlarında bırakır.
    ai_suggested: bool = False
    recommendation_source: Optional[str] = None
    recommendation_confidence: Optional[float] = None


@dataclass(frozen=True)
class GroupTransferCommand:
    """`ArtifactTransferService.execute_group`'un girdisi -- yalnızca
    sohbet/REST üzerinden birden fazla alıcıya aynı anda dağıtım
    (Faz 5, #205).

    Bilinçli olarak bir `channel` alanı yoktur: `execute_group` her zaman
    `execute()`'u `channel="chat"` ile çağırır (AI kanalının bunlardan
    birini neden asla oluşturmadığı için kendi docstring'ine bakın).
    """

    company_id: str
    sender: UserModel
    recipient_ids: tuple
    #: "draft" | "document"
    artifact_kind: str
    source_artifact_id: str
    source_version: Optional[int] = None
    #: Alıcı başına bir idempotency anahtarı türetmek için her
    #: `recipient_id` ile birleştirilir (`f"{prefix}:{recipient_id}"`) --
    #: her biri kendi `TransferCommand`/`ArtifactTransferModel` satırı
    #: olduğundan tek düz bir anahtar alıcılar arasında yeniden
    #: kullanılamaz. `None`, `TransferCommand.idempotency_key` ile aynı
    #: şekilde idempotency'yi tamamen atlar.
    idempotency_key_prefix: Optional[str] = None


@dataclass(frozen=True)
class GroupTransferResultItem:
    """Bir `execute_group` çağrısı içindeki tek bir alıcının sonucu --
    `app.domains.pools.schema.pool_schema.PoolPushResultItem`'ın kendi
    alıcı başına kısmi başarı şeklini yansıtır."""

    recipient_id: str
    #: "sent" | "denied" | "not_found" | "failed"
    status: str
    transfer_id: Optional[str] = None
    reason: Optional[str] = None


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
        """Dinleyici hatalarının isteği bozmasına izin vermeden bir alan
        (domain) olayı yayınlar. `DraftShareService._publish` ile aynı
        örüntü."""
        try:
            await event_bus.publish(event)
        except Exception:
            logger.exception("Failed to publish event %s", getattr(event, "event_type", "?"))

    async def execute(self, cmd: TransferCommand) -> ArtifactTransferModel:
        """Tek bir transferi uçtan uca çalıştırır: idempotency ->
        yetkilendirme -> politika -> anlık görüntü -> kayıt -> teslimat ->
        best-effort denetim/bildirim.

        Raises:
            NotFoundException: Belge veya alıcı, `cmd.company_id` içinde
                çözümlenmiyor.
            AuthorizationException: PDP, `Action.ARTIFACT_TRANSFER`'ı
                reddediyor ya da `TransferPolicy` daha dar bir nedenle
                reddediyor (kendine gönderim, aktif olmayan alıcı,
                yetersiz yetki veya -- yalnızca AI kanalı -- alıcı bir
                favori değil).

        Returns:
            Kalıcı hale getirilmiş `ArtifactTransferModel`. `cmd.
            idempotency_key`, mevcut bir transferle eşleştiğinde, o
            transfer olduğu gibi döndürülür ve yeni bir şey oluşturulmaz.
        """
        if cmd.idempotency_key:
            existing = await self.transfer_repository.get_by_idempotency_key(
                cmd.company_id, cmd.idempotency_key
            )
            if existing is not None:
                return existing

        try:
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
        except NotFoundException:
            transfer_metrics.ARTIFACT_TRANSFERS.labels(channel=cmd.channel, result="not_found").inc()
            raise

        recipient = await self.user_repository.get_by_id_in_company(cmd.recipient_id, cmd.company_id)
        if recipient is None:
            transfer_metrics.ARTIFACT_TRANSFERS.labels(channel=cmd.channel, result="not_found").inc()
            raise NotFoundException(message="Kullanıcı bulunamadı.")

        resource = Resource(
            type=cmd.artifact_kind, id=cmd.source_artifact_id, company_id=cmd.company_id, owner_id=owner_id
        )
        decision = authorize(subject_from_user(cmd.sender), Action.ARTIFACT_TRANSFER, resource)
        if not decision.permit:
            transfer_metrics.ARTIFACT_TRANSFERS.labels(channel=cmd.channel, result="denied").inc()
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
            transfer_metrics.TRANSFER_POLICY_DENIALS.labels(
                reason=policy_decision.reason_code or "unknown"
            ).inc()
            transfer_metrics.ARTIFACT_TRANSFERS.labels(channel=cmd.channel, result="denied").inc()
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
        transfer_metrics.ARTIFACT_TRANSFERS.labels(channel=cmd.channel, result="success").inc()
        return transfer

    async def execute_group(self, cmd: GroupTransferCommand) -> list:
        """Tek bir belgeyi tek bir çağrıda birden fazla alıcıya dağıtır --
        yalnızca sohbet/REST grup gönderim yolu (`POST
        /transfers/send-group`).

        Bilinçli olarak AI kanalından erişilemez: `app.ai.tools.
        transfer_tools.propose_transfer` ve `TransferGraphProvider` her
        zaman yalnızca tek alıcılı bir `TransferCommand` oluşturur/tek
        alıcılı bir intent açar -- her ikisinin de grup varyantı yoktur ve
        bu metot `app.ai.*`'dan asla çağrılmaz (burada bir çalışma zamanı
        kontrolüyle değil, mevcut `app.ai.*` asla `app.domains.*`'ı import
        etmez sınırıyla uygulanır).

        Her alıcı, bu sınıfın zaten sunduğu tam olarak aynı `execute()`'tan
        geçer -- ikinci bir transfer uygulaması yok, `execute()`'un kendi
        docstring'inin belirttiği aynı ilke -- böylece bir alıcı için
        reddetme (yetki, kendine gönderim, aktif değil, ...) diğerlerini
        asla engellemez. `PoolService.push`/`_push_one`'ın kendi alıcı
        başına kısmi başarı şeklini yansıtır.

        Raises:
            ValidationException: `cmd.recipient_ids` boş ya da
                `MAX_GROUP_TRANSFER_RECIPIENTS`'i aşıyor.
        """
        if not cmd.recipient_ids:
            raise ValidationException(message="En az bir alıcı gerekli.")
        if len(cmd.recipient_ids) > MAX_GROUP_TRANSFER_RECIPIENTS:
            raise ValidationException(
                message=(
                    f"Bir grup transferinde en fazla {MAX_GROUP_TRANSFER_RECIPIENTS} "
                    "alıcı olabilir."
                )
            )

        results: list[GroupTransferResultItem] = []
        for recipient_id in cmd.recipient_ids:
            idempotency_key = (
                f"{cmd.idempotency_key_prefix}:{recipient_id}"
                if cmd.idempotency_key_prefix
                else None
            )
            try:
                transfer = await self.execute(
                    TransferCommand(
                        company_id=cmd.company_id,
                        sender=cmd.sender,
                        recipient_id=recipient_id,
                        artifact_kind=cmd.artifact_kind,
                        source_artifact_id=cmd.source_artifact_id,
                        source_version=cmd.source_version,
                        channel="chat",
                        idempotency_key=idempotency_key,
                    )
                )
            except NotFoundException as exc:
                results.append(
                    GroupTransferResultItem(recipient_id=recipient_id, status="not_found", reason=exc.message)
                )
            except AuthorizationException as exc:
                results.append(
                    GroupTransferResultItem(recipient_id=recipient_id, status="denied", reason=exc.message)
                )
            except ValidationException as exc:
                results.append(
                    GroupTransferResultItem(recipient_id=recipient_id, status="failed", reason=exc.message)
                )
            else:
                results.append(
                    GroupTransferResultItem(recipient_id=recipient_id, status="sent", transfer_id=transfer.id)
                )
        return results

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
        """Alıcının kendi, hemen sahiplenilen kopyası -- bkz. planın §D5'i:
        bir `drafts` satırı zaten değişmez bir versiyondur, dolayısıyla
        "anlık görüntü" birini çatallamak anlamına gelir, `create_version`'ın
        diğer her revizyona zaten verdiği aynı mekanizma. Diğer her yeni
        taslak gibi alıcının kendi taslak kotasından düşer."""
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
