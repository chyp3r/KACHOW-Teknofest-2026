"""`FeedbackService` -- RLHF tarzı veri toplama katmanının yazma tarafı
(Faz C1, #183). Bugün burada yalnızca toplama yapılır: bu modülde eğitim
için bu satırları geri okuyan hiçbir şey yok. Bir oyun kimliğinin neden
mesaj id'si değil de `content_hash` olduğu için `FeedbackModel`'ın
docstring'ine bakın.
"""

import hashlib
from typing import List, Optional
from uuid import uuid4

from app.api.exceptions.not_found import NotFoundException
from app.domains.feedback.model.feedback_model import FeedbackModel
from app.domains.feedback.repository import FeedbackRepository


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()


class FeedbackService:
    def __init__(self, repository: FeedbackRepository):
        self.repository = repository

    async def submit(
        self,
        *,
        company_id: str,
        user_id: str,
        target_kind: str,
        signal: str,
        content: str,
        comment: Optional[str] = None,
        dimensions: Optional[dict] = None,
        session_id: Optional[str] = None,
        message_id: Optional[str] = None,
        draft_id: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> FeedbackModel:
        """Bir oy verir; aynı metin üzerinde mevcut bir oy varsa onun
        üzerine upsert yapar.

        Tam olarak aynı oylanan metin üzerinde ikinci bir oy (tekrar
        tıklama veya 👍→👎 değiştirme), yeni bir kayıt eklemek yerine
        mevcut satırın `signal`/`comment`/`dimensions`/`context`
        alanlarını yerinde günceller -- `uq_feedback_vote_identity` zaten
        yinelemeyi reddederdi, ancak bunu burada çözmek, çağıranın ikinci
        tıklamada bir kısıt ihlali hatası yerine her iki durumda da tutarlı
        tek bir satır almasını sağlar.
        """
        content_hash = _hash_content(content)
        existing = await self.repository.find_existing_vote(
            company_id, user_id, target_kind, content_hash
        )
        if existing is not None:
            return await self.repository.update_vote(
                existing, signal=signal, comment=comment, dimensions=dimensions, context=context
            )
        feedback = FeedbackModel(
            id=uuid4().hex,
            company_id=company_id,
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
            draft_id=draft_id,
            target_kind=target_kind,
            signal=signal,
            comment=comment,
            dimensions=dimensions,
            content_hash=content_hash,
            context=context,
        )
        return await self.repository.create(feedback)

    async def remove(self, feedback_id: str, company_id: str) -> FeedbackModel:
        feedback = await self.repository.get_by_id(feedback_id, company_id)
        if feedback is None:
            raise NotFoundException(message="Geri bildirim bulunamadı.")
        await self.repository.soft_delete(feedback)
        return feedback

    async def list_entries(
        self,
        company_id: str,
        user_id: Optional[str] = None,
        target_kind: Optional[str] = None,
        signal: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[FeedbackModel]:
        return await self.repository.list_filtered(
            company_id, user_id, target_kind, signal, skip=skip, limit=limit
        )

    async def count_entries(
        self,
        company_id: str,
        user_id: Optional[str] = None,
        target_kind: Optional[str] = None,
        signal: Optional[str] = None,
    ) -> int:
        return await self.repository.count_filtered(company_id, user_id, target_kind, signal)

    async def stats(self, company_id: str) -> dict:
        by_signal = await self.repository.count_by_signal(company_id)
        by_target_kind = await self.repository.count_by_target_kind(company_id)
        return {
            "total": sum(by_signal.values()),
            "likes": by_signal.get("like", 0),
            "dislikes": by_signal.get("dislike", 0),
            "by_target_kind": by_target_kind,
        }
