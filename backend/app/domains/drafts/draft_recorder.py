"""Her üretilen/revize edilen taslağın en iyi çaba (best-effort) ile kalıcılaştırılması.

`app.observability.run_recorder` ve `app.domains.chat.chat_recorder` ile aynı
gerekçe: her iki çağrı noktası -- durumsuz `/documents/draft` endpoint'inin
istek kapsamlı handler'ı ve `ChatService`'in tur-tamamlanma hook'u -- kendi
oturum yönetimi hikayelerini kurmaktansa tek bir yazma yolunda kalmaları daha
basit, ve özellikle `ChatService`, SSE streaming sırasında istek kapsamlı bir
`Depends(get_db)` oturumunun dışında çalışır (bkz. `chat_recorder`'ın kendi
docstring'i). Bu yüzden bu modül, tıpkı o ikisi gibi, her çağrıda kendi
kısa ömürlü oturumunu açıp kapatır.

Her fonksiyon kendi exception'larını yutar ve yalnızca loglar -- bir taslağı
kaydetmek, taslak üretiminin başarısız olmasının nedeni olmamalıdır.
"""

import logging
from typing import Optional

from app.core.config import settings
from app.domains.drafts.repository import DraftRepository
from app.domains.units.repository import UnitRepository
from app.infrastructure.database.session import tenant_session
from app.observability import company_metrics

logger = logging.getLogger(__name__)


async def attach_to_session(
    *, draft_id: str, session_id: str, company_id: Optional[str]
) -> bool:
    """Doğrudan API üzerinden oluşturulan bir taslağa, ilk revizyonundan önce bir chat oturumu ata.

    Bu, normal ``record_draft`` sorgusunun bu satırı üst (parent) olarak
    bulup versiyon 2'yi eklemesini sağlar; aksi halde yanlışlıkla ilgisiz
    yeni bir version-1 zinciri başlatılırdı. Zaten bir oturuma bağlı olan
    taslaklara dokunulmaz.
    """
    try:
        async with tenant_session(company_id) as session:
            repository = DraftRepository(session)
            draft = await repository.get_by_id(draft_id)
            if draft is None:
                return False
            if draft.session_id is not None:
                return draft.session_id == session_id
            await repository.attach_session(draft, session_id)
            await session.commit()
            return True
    except Exception:
        logger.exception("Failed to attach draft %s to session %s", draft_id, session_id)
        return False


async def record_draft(
    *,
    user_id: Optional[str],
    session_id: Optional[str],
    document_id: Optional[str],
    content: str,
    correspondence_type: Optional[str] = None,
    destination: Optional[str] = None,
    destination_justification: Optional[str] = None,
    status: Optional[str] = None,
    confidence_score: Optional[float] = None,
    requires_human_approval: Optional[bool] = None,
    attempts: Optional[int] = None,
    verification: Optional[dict] = None,
    judge: Optional[dict] = None,
    missing_information: Optional[list] = None,
    instructions: Optional[str] = None,
    company_id: Optional[str] = None,
) -> Optional[str]:
    """Yeni bir taslak versiyonu ekle ve id'sini döndür, kaydedilmediyse `None` döndür.

    `session_id` verildiğinde, o oturumun en son versiyonuna zincirlenir
    (bir revizyon); `None` olduğunda (chat oturumu olmayan doğrudan bir
    `/documents/draft` çağrısı), her zaman yeni bir version=1 taslağı
    başlatılır, çünkü karşısında önceki bir versiyonu bulacak bir anahtar
    yoktur.

    Args:
        company_id: Çağıranın kiracısı (tenant) -- doğrudan API yolunda
            `DraftService.generate_draft_and_route`'un kendi `company_id`
            parametresinden, chat yolunda ise `ChatService.
            _maybe_record_draft` üzerinden `PlanningState.company_id`'den
            gelir. Bu değer, `drafts` tablosu satır düzeyi güvenliğe (RLS)
            geçtiğinde bu yazmanın `WITH CHECK`'i geçmesi için taşınır.

    Returns:
        Yeni taslağın id'si, ya da geçmiş kaydı devre dışıysa veya yazma
        başarısız olduysa `None` -- çağıranlar boş bir `draft_id`'yi ölümcül
        bir hata gibi değil, tolere edilebilir bir durum gibi ele almalıdır.
    """
    if not settings.DRAFT_HISTORY_ENABLED:
        return None
    try:
        async with tenant_session(company_id) as session:
            repository = DraftRepository(session)
            parent = (
                await repository.get_latest_for_session(session_id)
                if session_id is not None
                else None
            )
            # Bir revizyon turunun planı yalnızca `["revise"]`'dir --
            # `routing` adımı yoktur (bkz. `app.ai.workflows.planner`), bu
            # yüzden `chat_service._maybe_record_draft` bu çağrıya
            # `destination=None` geçer. Birim önerisi bu versiyonun metni
            # *hakkında* bir meta veridir ve içerik revizyonu onu
            # değiştirmez; bu yüzden yeni değer boşsa üst versiyondan
            # devralınır -- aksi halde her revizyon "Hedef birim"i sıfırlar.
            # Gerçek bir `draft` turu (planında `routing` olan) yeni bir
            # öneri getirdiğinde `destination` dolu gelir ve devralma
            # tetiklenmez.
            parent_unit_id = None
            if parent is not None:
                if not destination:
                    destination = parent.destination
                    parent_unit_id = parent.destination_unit_id
                if not destination_justification:
                    destination_justification = parent.destination_justification

            # `destination`, routing graph'ın serbest metin birim *adı*dır --
            # burada, yazma anında, bir kere gerçek bir `units` satırına
            # çözümlenir; `DraftShareService.send`'in eskiden her
            # gönderimde tekrar yapmak zorunda olduğu aynı sorgu (bkz.
            # `drafts.destination_unit_id`'in kendi docstring'i). Bu
            # şirkette hiçbir birimle eşleşmeyen bir ad (yeniden
            # adlandırılmış, silinmiş ya da routing boş dönmüş) hataya
            # değil, `None`'a çözümlenir.
            destination_unit_id = None
            if destination and company_id:
                unit = await UnitRepository(session).get_by_name(destination, company_id)
                destination_unit_id = unit.id if unit else None
            # Ad üst versiyondan devralındıysa ama bu turda çözümlenemediyse
            # (company_id yok, ya da birim yeniden adlandırıldı) üst
            # versiyonun zaten çözülmüş id'sine düş.
            if destination_unit_id is None and parent_unit_id is not None:
                destination_unit_id = parent_unit_id
            draft = await repository.create_version(
                user_id=user_id,
                company_id=company_id,
                session_id=session_id,
                document_id=document_id,
                content=content,
                parent=parent,
                correspondence_type=correspondence_type,
                destination=destination,
                destination_unit_id=destination_unit_id,
                destination_justification=destination_justification,
                status=status,
                confidence_score=confidence_score,
                requires_human_approval=requires_human_approval,
                attempts=attempts,
                verification=verification,
                judge=judge,
                missing_information=missing_information,
                instructions=instructions,
            )
            await session.commit()
            if company_id is not None:
                slug = company_metrics.cached_slug(company_id)
                if slug is not None:
                    company_metrics.note_draft_created(slug, status)
            return draft.id
    except Exception:
        logger.exception("Failed to record draft for session %s", session_id)
        return None
