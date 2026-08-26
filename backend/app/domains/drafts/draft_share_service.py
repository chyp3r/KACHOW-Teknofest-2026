import logging
from typing import List, Optional, Tuple
from uuid import uuid4

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.core.permissions.role_checker import bypasses_ownership
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.model.draft_share_model import DraftShareModel
from app.domains.drafts.repository import DraftRepository, DraftShareRepository
from app.domains.drafts.schema.draft_share_schema import DraftSendRequest
from app.domains.transfers.service import ArtifactTransferService, TransferCommand
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.events.event import DraftShareRespondedEvent
from app.events.event_bus import event_bus

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = ("sent", "read")


class DraftShareService:
    """`draft_shares` için servis -- çalışanlar arası taslak gönder/al akışı.

    `send` artık transferi kendisi gerçekleştirmiyor -- işin tamamını
    (yetkilendirme, politika, fork, teslimat, denetim kaydı, bildirim)
    her artifact transferinin artık geçtiği tek yol olan
    `ArtifactTransferService.execute(channel="rest")`'e devrediyor (bkz. o
    servisin kendi docstring'i). Burada kalan yalnızca bu tablonun kendi
    tüketicilerinin (`GET /drafts/inbox`, `/outbox`, accept/reject/withdraw
    rotaları) hâlâ ihtiyaç duyduğu `draft_shares`'e özgü inbox/outbox/kabul/
    ret muhasebesi -- ABAC/politika kararını tekrarlamaz, yalnızca gerçek
    transferin yanında bir paylaşımın gerçekleştiğini kaydeder.

    Zaten oluşturulmuş bir paylaşımı görüntülemek/yanıtlamak ABAC kararı
    *değildir*: bir `draft_shares` satırının `recipient_id`/`sender_id`'si
    zaten yetkilendirmenin kendisidir (yalnızca iki taraf, ya da
    `bypasses_ownership` üzerinden şirket çapında ADMIN/MANAGER/ROOT ona
    dokunabilir) -- burada altta yatan `drafts` satırına karşı bir
    `draft:read` kontrolü yoktur ve bu kasıtlıdır: taslağın sahibi olmayan
    ve ADMIN/MANAGER/ROOT olmayan bir alıcı bu kontrolü geçemezdi, ama yine
    de kendisine gönderileni okuyabilmelidir. Paylaşım satırı (her yanıtta
    taslağın içeriğiyle join edilmiş halde -- bkz. `DraftShareResponse`)
    erişim yetkisinin kendisidir, taslağın sahipliği değil.
    """

    def __init__(
        self,
        share_repository: DraftShareRepository,
        draft_repository: DraftRepository,
        user_repository: UserRepository,
        transfer_service: ArtifactTransferService,
    ):
        self.share_repository = share_repository
        self.draft_repository = draft_repository
        self.user_repository = user_repository
        self.transfer_service = transfer_service

    @staticmethod
    async def _publish(event) -> None:
        """Bir domain event'i, listener hatalarının isteği bozmasına izin vermeden yayınla.

        `app.domains.documents.service.DocumentService._publish` ile aynı desen.
        """
        try:
            await event_bus.publish(event)
        except Exception:
            logger.exception("Failed to publish event %s", getattr(event, "event_type", "?"))

    async def send(
        self, draft_id: str, sender: UserModel, request: DraftSendRequest, company_id: str
    ) -> List[DraftShareModel]:
        """Bir taslak versiyonunu bir veya birden fazla alıcıya gönder.

        Her alıcı kendi `ArtifactTransferService.execute` çağrısından geçer
        -- yetkilendirme, politika, fork, teslimat ve bildirim hepsi orada
        gerçekleşir (bkz. kendi docstring'i). Bu metodun eski, tek parça
        implementasyonunun aksine, çok alıcılı bir gönderim artık kesin
        anlamda hep-ya-da-hiç değildir: önceki bir alıcı için zaten
        gerçekleşmiş bir transfer, sonraki bir alıcının kendi politika
        kontrolü başarısız olsa bile (kendine gönderme, pasif alıcı,
        yetersiz yetki) gerçekleşmiş olarak kalır -- her kanalı tek bir
        transfer yoluna birleştirmek, yalnızca gerçek bir transfer servisi
        henüz var olmadığı için var olan bir batch-atomiklik garantisini
        korumaktan daha önceliklidir. Pratikte bu yalnızca gerçekten çok
        alıcılı bir gönderimde önem taşır ki bunu ne bu endpoint'in kendi
        frontend tüketicisi (böyle bir şey yok) ne de yeni chat-composer
        gönderim akışı (yapısı gereği tek alıcılı) hiç kullanmaz.

        Raises:
            NotFoundException: `draft_id`, `company_id` içinde
                çözümlenmiyorsa, ya da (`ArtifactTransferService.execute`
                üzerinden) bir `recipient_ids` girdisi çözümlenmiyorsa.
            AuthorizationException: `sender`'ın bu spesifik taslağı
                göndermesine izin yoksa, ya da `TransferPolicy` daha dar bir
                sebeple reddediyorsa (kendine gönderme, pasif alıcı).
        """
        draft = await self.draft_repository.get_by_id(draft_id)
        if draft is None:
            raise NotFoundException(message="Taslak bulunamadı.")

        shares: List[DraftShareModel] = []
        for recipient_id in request.recipient_ids:
            await self.transfer_service.execute(
                TransferCommand(
                    company_id=company_id,
                    sender=sender,
                    recipient_id=recipient_id,
                    artifact_kind="draft",
                    source_artifact_id=draft.id,
                    source_version=draft.version,
                    channel="rest",
                )
            )
            share = await self.share_repository.create(
                DraftShareModel(
                    id=uuid4().hex,
                    company_id=company_id,
                    draft_id=draft.id,
                    sender_id=sender.id,
                    recipient_id=recipient_id,
                    # Zaten taslak yazma anında bir kere çözümlendi (bkz.
                    # `drafts.destination_unit_id`'in kendi docstring'i) --
                    # artık her gönderimde ayrı bir ad sorgusuna gerek yok.
                    suggested_unit_id=draft.destination_unit_id,
                    message=request.message,
                    status="sent",
                )
            )
            shares.append(share)
        return shares

    async def list_inbox(
        self, company_id: str, user_id: str, status: Optional[str], skip: int, limit: int
    ) -> Tuple[List[Tuple[DraftShareModel, DraftModel]], int]:
        items = await self.share_repository.list_inbox(
            company_id, user_id, status=status, skip=skip, limit=limit
        )
        total = await self.share_repository.count_inbox(company_id, user_id, status=status)
        return items, total

    async def list_outbox(
        self, company_id: str, user_id: str, status: Optional[str], skip: int, limit: int
    ) -> Tuple[List[Tuple[DraftShareModel, DraftModel]], int]:
        items = await self.share_repository.list_outbox(
            company_id, user_id, status=status, skip=skip, limit=limit
        )
        total = await self.share_repository.count_outbox(company_id, user_id, status=status)
        return items, total

    async def _get_owned_share(
        self, share_id: str, company_id: str, requester: UserModel
    ) -> Tuple[DraftShareModel, DraftModel]:
        share = await self.share_repository.get_by_id(share_id, company_id)
        if share is None:
            raise NotFoundException(message="Paylaşım bulunamadı.")
        if (
            requester.id not in (share.sender_id, share.recipient_id)
            and not bypasses_ownership(requester)
        ):
            raise AuthorizationException(message="Bu paylaşıma erişim izniniz yok.")
        draft = await self.draft_repository.get_by_id(share.draft_id)
        return share, draft

    async def mark_read(
        self, share_id: str, company_id: str, requester: UserModel
    ) -> Tuple[DraftShareModel, DraftModel]:
        share, draft = await self._get_owned_share(share_id, company_id, requester)
        if share.recipient_id != requester.id:
            raise AuthorizationException(message="Yalnızca alıcı okundu olarak işaretleyebilir.")
        share = await self.share_repository.mark_read(share)
        return share, draft

    async def respond(
        self, share_id: str, company_id: str, requester: UserModel, status: str, response_note: Optional[str]
    ) -> Tuple[DraftShareModel, DraftModel]:
        """`requester`'a adreslenmiş bir paylaşımı kabul et veya reddet.

        Artık yalnızca bir durum geçişi -- artık bir taslak versiyonu fork
        etmiyor. Alıcı zaten *gönderim* anında kendi, doğrudan sahip
        olduğu kopyayı almıştı (`ArtifactTransferService.execute`'ın taslak
        fork'u, bkz. kendi docstring'i), bu yüzden bir paylaşımı kabul
        etmek, tıpkı `mark_read`'in zaten yaptığı gibi, sadece teslimatı
        onaylamaktır. Bunun üzerine burada tekrar fork yapmak, alıcının hiç
        istemediği ikinci, sahipsiz bir kopya üretirdi -- bu değişikliğin
        ortadan kaldırdığı tam da o çifte fork (bkz. planın kendi §D5'i).

        Raises:
            NotFoundException: `share_id` çözümlenmiyorsa.
            AuthorizationException: `requester`, paylaşımın
                `recipient_id`'si değilse, ya da paylaşım artık
                `sent`/`read` durumunda değilse (zaten sonuçlanmış ya da
                geri çekilmiş).
        """
        share, draft = await self._get_owned_share(share_id, company_id, requester)
        if share.recipient_id != requester.id:
            raise AuthorizationException(message="Yalnızca alıcı yanıt verebilir.")
        if share.status not in _ACTIVE_STATUSES:
            raise AuthorizationException(message="Bu paylaşım zaten yanıtlanmış veya geri çekilmiş.")

        share = await self.share_repository.respond(share, status, response_note)

        await self._publish(
            DraftShareRespondedEvent(
                payload={
                    "company_id": company_id,
                    "share_id": share.id,
                    "draft_id": share.draft_id,
                    "sender_id": share.sender_id,
                    "recipient_id": share.recipient_id,
                    "recipient_username": requester.username,
                    "status": status,
                    "response_note": response_note,
                }
            )
        )
        return share, draft

    async def withdraw(self, share_id: str, company_id: str, requester: UserModel) -> DraftShareModel:
        share, _draft = await self._get_owned_share(share_id, company_id, requester)
        if share.sender_id != requester.id and not bypasses_ownership(requester):
            raise AuthorizationException(message="Yalnızca gönderen geri çekebilir.")
        if share.status != "sent":
            raise AuthorizationException(message="Yalnızca 'sent' durumundaki bir paylaşım geri çekilebilir.")
        return await self.share_repository.withdraw(share)
