"""Her planning-graph run'ının karar izinin best-effort kalıcılaştırılması.

Planning graph her process için bir kez derlenir (bkz.
``app.api.dependency.get_planning_graph``) ve node'ları düz closure'lardır
-- bir FastAPI endpoint'inin ``Depends(get_db)`` üzerinden aldığı gibi
istek kapsamlı bir ``AsyncSession`` asla almazlar. Buradaki her fonksiyon
bunun yerine kendi kısa ömürlü session'ını açar ve kapatır; tek seferlik
bir bağlantı kontrolünde (``app.infrastructure.database.session.
verify_db_connection``) zaten kullanılan aynı desen.

Her fonksiyon kendi exception'larını yutar ve sadece loglar -- bir run'ı
kaydetmek bir sohbet turunun başarısız olmasının nedeni olmamalıdır. Bu,
Langfuse tracing'in (``app.observability.tracer``) ve bu kod tabanındaki
diğer her ikincil yan etkinin (event bus publish'leri, doküman sahiplik
kaydı) hata fırlatmak yerine "kaydedilmedi" durumuna bozulma şeklini
yansıtır.
"""

import logging
from typing import Any, Optional
from uuid import uuid4

from app.core.config import settings
from app.infrastructure.database.session import tenant_session
from app.observability.model.run_model import RunModel, RunStepModel

logger = logging.getLogger(__name__)


async def start_run(
    *,
    run_id: str,
    thread_id: str,
    user_id: Optional[str],
    document_id: Optional[str],
    input_text: str,
    intent: str,
    plan_steps: list[str],
    source: str,
    confidence: float,
    evidence: tuple[str, ...],
    alternatives: tuple[tuple[str, float], ...],
    clarification: Optional[dict[str, Any]],
    company_id: Optional[str] = None,
) -> None:
    """Planning tamamlandığı anda bir run'ın çözülmüş planını kaydeder.

    Args:
        run_id: Bu turun run id'si (bkz. ``PlanningState.run_id``).
        thread_id: Bu run'ın ait olduğu checkpointer thread'i.
        user_id: Kimliği doğrulanmış çağıran, biliniyorsa.
        document_id: Varsa eklenen doküman.
        input_text: Kullanıcının bu turdaki mesajı.
        intent, plan_steps, source, confidence, evidence, alternatives,
            clarification: ``resolve_plan``'ın ürettiği ``PlanDecision``'ın
            (bkz. ``app.ai.workflows.planner.PlanDecision``) her alanı.
        company_id: Çağıranın tenant'ı (``ChatService._invoke`` tarafından
            ayarlanan ``PlanningState.company_id``). Bu INSERT'in, o tablo
            buna geçirildiğinde ``runs``'ın row-level-security
            ``WITH CHECK``'ini geçmesi için taşınır (bkz. ``tenant_session``)
            -- ``None``, diğer her recorder hatasında olduğu gibi hata
            fırlatmak yerine aşağıdaki try/except üzerinden "kaydedilmedi"
            durumuna bozulur.
    """
    if not settings.RUN_RECORDING_ENABLED:
        return
    try:
        async with tenant_session(company_id) as session:
            session.add(
                RunModel(
                    id=run_id,
                    company_id=company_id,
                    thread_id=thread_id,
                    user_id=user_id,
                    document_id=document_id,
                    input_text=input_text,
                    intent=intent,
                    plan_steps=list(plan_steps),
                    source=source,
                    confidence=confidence,
                    evidence=list(evidence),
                    alternatives=[list(item) for item in alternatives],
                    clarification=clarification,
                    status="running",
                )
            )
            await session.commit()
    except Exception:
        logger.exception("Failed to record run start for %s", run_id)


async def record_step(
    *,
    run_id: str,
    step: str,
    status: str,
    duration_ms: float,
    error: Optional[str] = None,
    company_id: Optional[str] = None,
) -> None:
    """Bir plan adımının sonucunu kaydeder (bkz. ``_execute_one_step``).

    ``run_id`` boş olduğunda hiçbir şey yapmaz -- checkpoint'i bu alandan
    öncesine ait olan devam ettirilmiş bir run'ın (veya ``planning_node``
    üzerinden geçmeden oluşturulan herhangi bir state'in) adımı
    iliştirecek hiçbir şeyi yoktur.

    Args:
        company_id: :func:`start_run`'ın docstring'ine bakın -- aynı
            gerekçe, ``run_id``'nin olduğu gibi ``run_steps`` üzerine
            denormalize edilmiştir.
    """
    if not settings.RUN_RECORDING_ENABLED or not run_id:
        return
    try:
        async with tenant_session(company_id) as session:
            session.add(
                RunStepModel(
                    id=uuid4().hex,
                    company_id=company_id,
                    run_id=run_id,
                    step=step,
                    status=status,
                    duration_ms=duration_ms,
                    error=error,
                )
            )
            await session.commit()
    except Exception:
        logger.exception("Failed to record run step '%s' for run %s", step, run_id)


async def end_run(*, run_id: str, status: str, company_id: Optional[str] = None) -> None:
    """Terminal node çalıştığında bir run'ın durumunu kapatır.

    ``run_id`` boş olduğunda hiçbir şey yapmaz, :func:`record_step` ile
    aynı gerekçe. Human-in-the-loop kapısında duraklayan ve bir daha
    devam ettirilmeyen bir run için asla tetiklenmez -- "running" olarak
    kalır; süpürülmüş veya zaman aşımına uğramış değil, terk edilmiş bir
    run'ın dürüst bir yansımasıdır.

    Args:
        company_id: :func:`start_run`'ın docstring'ine bakın. Bu bir INSERT
            değil, bir UPDATE'tir -- ``runs`` row-level security altına
            girdiğinde, bunun ayarladığı GUC sadece bir WITH CHECK'in
            doğruladığı şey değil, satırın *bulunmasını* sağlayan şeydir.
    """
    if not settings.RUN_RECORDING_ENABLED or not run_id:
        return
    try:
        async with tenant_session(company_id) as session:
            run = await session.get(RunModel, run_id)
            if run is None:
                return
            run.status = status
            await session.commit()
    except Exception:
        logger.exception("Failed to record run end for %s", run_id)
