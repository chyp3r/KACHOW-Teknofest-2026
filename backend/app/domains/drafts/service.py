from typing import List, Optional

from app.api.exceptions.not_found import NotFoundException
from app.api.exceptions.validation import ValidationException
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.repository import DraftRepository
from app.domains.units.repository import UnitRepository


class DraftService:
    """Drafts API için iş mantığı.

    Oluşturma, `app.domains.documents.draft_service.DraftService.
    generate_draft_and_route`'tan ve `ChatService`'ten çağrılan
    `app.domains.drafts.draft_recorder` üzerinden gerçekleşir -- ikisi de
    istek kapsamlı bir oturumun dışında çalışır (ikincisi SSE streaming
    sırasında), bu yüzden bu servisten geçmek yerine kendi
    oturum/repository'lerine sahiptirler. `delete_draft`, bu servisin
    sahip olduğu tek yazma işlemidir: drafts router'ının zaten sahip
    olduğu istek kapsamlı oturum içinde çalışır, etrafından dolaşılması
    gereken bir SSE-streaming derdi yoktur.
    """

    def __init__(self, repository: DraftRepository) -> None:
        self.repository = repository

    async def get_draft(self, draft_id: str) -> DraftModel:
        draft = await self.repository.get_by_id(draft_id)
        if draft is None:
            raise NotFoundException(message="Draft not found.")
        return draft

    async def list_versions(self, draft_id: str) -> List[DraftModel]:
        """Taslağın zincirindeki tüm versiyonlar, en eskiden en yeniye.

        Taslağı yalnızca `session_id`'sini çözümlemek için önce arar --
        doğrudan API taslağının (`session_id=None`) versiyon zinciri tek
        bir taslağa indirgenir, çünkü zincirlenecek başka bir şey yoktur.
        """
        draft = await self.get_draft(draft_id)
        if draft.session_id is None:
            return [draft]
        return await self.repository.list_versions_for_session(draft.session_id)

    async def list_drafts(
        self,
        company_id: Optional[str] = None,
        session_id: Optional[str] = None,
        document_id: Optional[str] = None,
        user_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[DraftModel]:
        return await self.repository.list_drafts(
            company_id=company_id,
            session_id=session_id,
            document_id=document_id,
            user_id=user_id,
            skip=skip,
            limit=limit,
        )

    async def count_drafts(
        self,
        company_id: Optional[str] = None,
        session_id: Optional[str] = None,
        document_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> int:
        return await self.repository.count_drafts(
            company_id=company_id, session_id=session_id, document_id=document_id, user_id=user_id
        )

    async def delete_draft(self, draft_id: str) -> None:
        """Bir taslağı ve ait olduğu tüm versiyon zincirini soft-delete yap.

        Raises:
            NotFoundException: `draft_id` mevcut değilse (ya da zaten
                silinmişse -- `get_by_id`, `is_deleted`'i filtreler, bu
                yüzden ikinci bir silme çağrısı sessizce başarılı olmak
                yerine eksik bir taslakla aynı şekilde raporlanır).
        """
        draft = await self.get_draft(draft_id)
        if draft.session_id is None:
            await self.repository.soft_delete(draft_id)
        else:
            await self.repository.soft_delete_session(draft.session_id)

    async def update_destination(self, draft_id: str, destination: str, company_id: str) -> DraftModel:
        """Bu taslak versiyonunun yönlendirildiği birimi çağıranın kendi seçimiyle geçersiz kıl.

        Routing graph artık her zaman birincil + (genellikle) bir alternatif
        önerir (bkz. `app.ai.workflows.routing_graph._best_effort_unit`),
        ama bir insan yine de üçüncü bir seçenek isteyebilir -- bu, ör.
        chat UI'ın birim seçicisinden gelen o durum için yazma yoludur.
        `destination`'ın gerçek bir birimle eşleşmesi gerekmez: özel,
        serbest metin bir hedef, routing'in kendi fallback'inin eşleşmeyen
        bir adı zaten tolere ettiği şekilde kabul edilir (bkz.
        `DraftModel.destination_unit_id`'in docstring'i) -- yalnızca
        `destination_unit_id` olmadan çözümlenir.

        Args:
            draft_id: Düzeltilmekte olan spesifik versiyon -- illa
                oturumun en sonuncusu değil (daha eski bir versiyonun
                yönlendirmesi de sonradan düzeltilebilir).
            destination: Seçilen birimin adı, boş olamaz.
            company_id: Çağıranın kiracısı; `destination`'ı bu şirketin
                kendi `units`'ine karşı (başka bir kiracınınkine değil)
                çözümlemek için kullanılır.

        Raises:
            NotFoundException: `draft_id` mevcut değilse.
            ValidationException: `destination` boşsa.

        Returns:
            Güncellenmiş taslak satırı.
        """
        destination = destination.strip()
        if not destination:
            raise ValidationException(message="Birim adı boş olamaz.")
        draft = await self.get_draft(draft_id)
        unit = await UnitRepository(self.repository.db).get_by_name(destination, company_id)
        return await self.repository.update_destination(
            draft,
            destination=destination,
            destination_unit_id=unit.id if unit else None,
            destination_justification="Kullanıcı tarafından manuel olarak seçildi.",
        )
