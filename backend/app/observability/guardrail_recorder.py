"""Koruma kararlarının en iyi çaba (best-effort) kalıcılığı (bkz.
``GuardrailEventModel``).

``app.observability.run_recorder``'ın kardeşi: aynı kısa ömürlü oturum
deseni (düğümler, istek kapsamlı bir ``AsyncSession``'ı olmayan sade
closure'lardır), aynı "kayıt işlemi gerçek isteği asla bozmasın" yutup-günlükle
sözleşmesi ve ikinci bir bayrak eklemek yerine ``settings.RUN_RECORDING_ENABLED``'ı
yeniden kullanır -- bir koruma olayı, farklı bir karar için de olsa bir run
ile aynı türde bir denetim kaydıdır.
"""

import logging
from typing import Optional
from uuid import uuid4

from app.core.config import settings
from app.infrastructure.database.session import tenant_session
from app.observability import company_metrics
from app.observability.ai_metrics import GUARDRAIL_DECISIONS
from app.observability.model.guardrail_model import GuardrailEventModel

logger = logging.getLogger(__name__)


async def record_event(
    *,
    stage: str,
    kind: str,
    decision: str,
    confidence: float = 1.0,
    reasons: Optional[list[str]] = None,
    run_id: Optional[str] = None,
    document_id: Optional[str] = None,
    company_id: Optional[str] = None,
    requester_user_id: Optional[str] = None,
    requester_role: Optional[str] = None,
    effective_clearance: Optional[str] = None,
    related_document_ids: Optional[list[str]] = None,
    llm_model_version: Optional[str] = None,
    prompt_template_version: Optional[str] = None,
) -> None:
    """Bir koruma kararını kaydet.

    Args:
        stage: "input" veya "output".
        kind: "pii" | "sensitivity" | "injection" | "magic_byte" |
            "archive_bomb" | "groundedness" | "leakage" | "llm_judge" |
            "relevance" (bkz. ``app.ai.workflows.relevance``).
        decision: "passed" | "flagged" | "blocked" | "redacted" |
            "needs_review".
        confidence: Karara dair 0-1 arası güven.
        reasons: Kısa, insan tarafından okunabilir gerekçeler -- kararı
            tetikleyen ham hassas değer asla değil (bkz. yalnızca maskelenmiş
            bir önizleme taşıyan ``app.ai.guardrails.pii.PiiFinding``, tam
            olarak bu nedenle).
        run_id: Bu kararın ait olduğu planlama grafiği çalışması, varsa
            (bir yükleme zamanı bulgusunun henüz bir tanesi yoktur).
        document_id: Bu kararın ilgilendiği doküman, varsa.
        company_id: Bu kararın ilgilendiği kiracı -- grafik içi olanlar dahil
            (bkz. ``PlanningState.company_id``) her çağrı noktasından
            iletilir. Yalnızca gerçekten çözümlenemeyen bir durumda ``None``;
            aşağıdaki yazma işlemi, diğer herhangi bir kaydedici hatasında
            olduğu gibi hata fırlatmak yerine "kaydedilmedi"ye düşer.
        requester_user_id, requester_role, effective_clearance: Kimin
            sorduğu ve hangi yetki düzeyinde -- RBAC katmanı (Faz 4)
            kararı atfedecek gerçek bir istek sahibine sahip olduğunda
            doldurulur; açık demo/geliştirme yolunda ``None``,
            ``DocumentModel.owner_id``'nin aynı kimlik doğrulamaya kadar
            nullable desenine uygun şekilde.
        related_document_ids: Bu turda bir yanıtın yararlandığı her doküman.
        llm_model_version, prompt_template_version: Bir LLM-yargıç katmanı
            (Faz 3) devredeyken bu kararı hangi model etiketinin ve şablon
            revizyonunun ürettiği.
    """
    # Aşağıdaki DB yazımının aksine koşulsuz: bir Prometheus sayacı bir
    # denetim kaydı değil metriktir ve bir dağıtım, DB yazımını atlamak için
    # RUN_RECORDING_ENABLED'ı kapatsa bile canlı kalmalıdır.
    GUARDRAIL_DECISIONS.labels(stage=stage, kind=kind, decision=decision).inc()
    if decision == "blocked" and company_id is not None:
        slug = company_metrics.cached_slug(company_id)
        if slug is not None:
            company_metrics.note_guardrail_block(slug, kind)

    if not settings.RUN_RECORDING_ENABLED:
        return
    try:
        async with tenant_session(company_id) as session:
            session.add(
                GuardrailEventModel(
                    id=uuid4().hex,
                    run_id=run_id,
                    document_id=document_id,
                    company_id=company_id,
                    stage=stage,
                    kind=kind,
                    decision=decision,
                    confidence=confidence,
                    reasons=list(reasons or []),
                    requester_user_id=requester_user_id,
                    requester_role=requester_role,
                    effective_clearance=effective_clearance,
                    related_document_ids=list(related_document_ids or []),
                    llm_model_version=llm_model_version,
                    prompt_template_version=prompt_template_version,
                )
            )
            await session.commit()
    except Exception:
        logger.exception(
            "Failed to record guardrail event (stage=%s kind=%s document=%s)",
            stage,
            kind,
            document_id,
        )
