"""Deterministik, DB tabanlı "gönder' hangi belgeye işaret ediyor" çözümlemesi.

AI kanalının `propose_transfer` aracının (`app.ai.tools.transfer_tools`,
assist adımının kendi modeli tarafından çağrılır) "son taslağı Ahmet'e
gönder" gibi bir mesajın "hangi taslağa" (ya da "hangi evraka") işaret
ettiğini yanıtlaması gerekir -- bunu, tur bazlı olan ve
`ACTIVE_DRAFT_IDLE_LIMIT` boşta tur sonunda kendiliğinden temizlenen
`SessionFocus.active_draft`'a güvenmeden yapmalıdır (bkz.
`app.ai.session.focus`'un kendi docstring'i). Taslak oluşturan, birkaç tur
alakasız iş yapan ve ancak sonra göndermek isteyen bir kullanıcı yine de
doğru şekilde çözümlenebilmelidir -- bu modül, bellek içi focus kanalı
yerine veritabanına giderek bunu sağlar.

Merdiven (plan §C2), taslak ve evrak için aynı üç katmanı çalıştırır:

1. Çağıran tarafından zaten çözümlenmiş açık bir referans (gerçek bir
   `drafts.id`/evrak depolama yolu -- burada asla serbest metinden tahmin
   edilmez; bu, tahmin işini sadece başka bir fonksiyona taşımak olurdu).
2. Thread'in kendi en son taslağı/evrakı -- herhangi bir sayıda boşta tur
   sonrasında bile geçerliliğini korur, çünkü boşta tur kavramı olmayan
   düz bir `updated_at`/`created_at` sorgusudur.
3. Thread'de hiçbir şey yoksa, isteği yapan kullanıcının şirket genelindeki
   en son taslakları/evrakları -- kendisi hiç taslak oluşturmamış bir
   oturumu kapsar (kullanıcı bunun yerine `/drafts` veya `/documents`'tan
   gelmiştir).

Herhangi bir katmanda birden fazla aday varsa `"ambiguous"` olarak
işaretlenir, birini seçerek asla çözümlenmez -- `RecipientResolutionService`
ile aynı şekilde, LLM burada seçim yapmaz.
"""

from dataclasses import dataclass
from typing import Literal, Optional, Sequence, Union

from app.domains.documents.model.document_model import DocumentModel
from app.domains.documents.repository import DocumentRepository
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.repository import DraftRepository

#: Kullanışsız uzun bir liste göstermek yerine kullanıcıdan daha spesifik
#: olmasını istemeden önce, katman 3'ün şirket genelinde sunacağı azami
#: aday sayısı.
DEFAULT_CANDIDATE_LIMIT = 5

Artifact = Union[DraftModel, DocumentModel]


@dataclass(frozen=True)
class ArtifactResolution:
    """Tek bir belge referansının çözümleme sonucu.

    Attributes:
        status: `"resolved"` (tam olarak bir aday), `"ambiguous"` (birden
            fazla -- çağıran belirsizliği gidermelidir, asla tahmin
            edilmez) ya da `"unresolved"` (hiçbir katmanda bulunamadı).
        artifact_kind: `"draft"` | `"document"`.
        candidates: `"unresolved"` için boş, `"resolved"` için tam olarak
            bir, `"ambiguous"` için iki veya daha fazla.
    """

    status: Literal["resolved", "ambiguous", "unresolved"]
    artifact_kind: Literal["draft", "document"]
    candidates: tuple


class ArtifactResolutionService:
    def __init__(self, draft_repository: DraftRepository, document_repository: DocumentRepository):
        self.draft_repository = draft_repository
        self.document_repository = document_repository

    async def resolve_draft(
        self,
        *,
        company_id: str,
        user_id: str,
        thread_id: Optional[str],
        explicit_draft_id: Optional[str] = None,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> ArtifactResolution:
        """Bu modülün merdivenine göre kullanıcının kastettiği "taslağı" çözümler.

        Args:
            company_id: Kiracı (tenant) kapsamı.
            user_id: İsteği yapan kullanıcı -- katman 3 yalnızca *kendi*
                taslaklarına bakar, şirketinkine asla bakmaz.
            thread_id: Sohbet oturumu id'si (`DraftModel.session_id`'nin
                karşılığı) -- katman 2'nin anahtarı. `draft_recorder.
                record_draft` sohbette üretilen her taslağı bu aynı id
                altında yazar, dolayısıyla bu tam olarak "bu konuşmanın
                şimdiye kadar ürettikleri"dir.
            explicit_draft_id: Çağıranın zaten çözümlediği bir referans
                (katman 1), örn. mesaj işaret zamiri gibi okunduğunda
                ("bu taslağı") `SessionFocus.active_draft_id`'den gelir.
                `None` bu katmanı tamamen atlar.
            candidate_limit: Katman 3'ün üst sınırı.
        """
        if explicit_draft_id:
            draft = await self.draft_repository.get_by_id(explicit_draft_id)
            if draft is not None and draft.company_id == company_id:
                return ArtifactResolution(status="resolved", artifact_kind="draft", candidates=(draft,))

        if thread_id:
            draft = await self.draft_repository.get_latest_for_session(thread_id)
            if draft is not None and draft.company_id == company_id:
                return ArtifactResolution(status="resolved", artifact_kind="draft", candidates=(draft,))

        candidates: Sequence[DraftModel] = await self.draft_repository.list_drafts(
            company_id=company_id, user_id=user_id, limit=candidate_limit
        )
        return _resolution_from_candidates("draft", candidates)

    async def resolve_document(
        self,
        *,
        company_id: str,
        user_id: str,
        explicit_document_id: Optional[str] = None,
        focus_document_id: Optional[str] = None,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> ArtifactResolution:
        """Kullanıcının kastettiği "evrakı" çözümler -- aynı merdiven şekli,
        ancak burada katman 2, bir oturum sorgusu yerine
        `SessionFocus.active_document_id`'dir, çünkü evraklar taslaklar
        gibi oturum bazında versiyonlanmaz.
        """
        for document_id in (explicit_document_id, focus_document_id):
            if not document_id:
                continue
            document = await self.document_repository.get_by_id(document_id, company_id)
            if document is not None:
                return ArtifactResolution(status="resolved", artifact_kind="document", candidates=(document,))

        candidates: Sequence[DocumentModel] = await self.document_repository.list_for_owner(
            company_id, user_id, limit=candidate_limit
        )
        return _resolution_from_candidates("document", candidates)


def _resolution_from_candidates(
    artifact_kind: Literal["draft", "document"], candidates: Sequence[Artifact]
) -> ArtifactResolution:
    if not candidates:
        return ArtifactResolution(status="unresolved", artifact_kind=artifact_kind, candidates=())
    if len(candidates) == 1:
        return ArtifactResolution(status="resolved", artifact_kind=artifact_kind, candidates=tuple(candidates))
    return ArtifactResolution(status="ambiguous", artifact_kind=artifact_kind, candidates=tuple(candidates))
