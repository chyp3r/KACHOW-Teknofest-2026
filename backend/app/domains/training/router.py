import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llms import get_fast_llm_client
from app.api.dependency import require_roles
from app.api.exceptions.authorization import AuthorizationException
from app.api.responses import APIResponse, SuccessResponse
from app.core.enums.user_role import UserRole
from app.domains.audit.repository import AuditLogRepository
from app.domains.audit.service import AuditService
from app.domains.quotas.repository import CompanyQuotaRepository, UsageCounterRepository
from app.domains.quotas.service import TRAINING_RUNS_METRIC, QuotaService
from app.domains.training.repository import TrainingRepository
from app.domains.training.schema.training_schema import (
    TrainingRunResponse,
    TrainingSampleResponse,
    TrainingSampleStatsResponse,
)
from app.domains.training.service import LORA_KINDS, STYLE_ADAPTER_KIND, TrainingService
from app.domains.users.model.user_model import UserModel
from app.infrastructure.database.session import get_db
from app.shared.dto.pagination import PaginatedResponse, PaginationParam

#: /companies altında kayıtlıdır -- app.domains.feedback.router.company_router
#: ile aynı biçimde.
company_router = APIRouter(prefix="/companies", tags=["training"])

#: Tek bir çıplak-id rotası (bir örneği silme) kendi router'ında yaşar,
#: app.domains.feedback.router'ın /feedback ile /companies/{id}/feedback/*
#: için kullandığı bölünmenin aynısı.
router = APIRouter(prefix="/training-samples", tags=["training"])


def _service(db: AsyncSession) -> TrainingService:
    return TrainingService(TrainingRepository(db))


def _audit_service(db: AsyncSession) -> AuditService:
    return AuditService(AuditLogRepository(db))


def _quota_service(db: AsyncSession) -> QuotaService:
    return QuotaService(UsageCounterRepository(db), CompanyQuotaRepository(db))


def _require_company_access(current_user: UserModel, company_id: str) -> None:
    """Root herhangi bir şirkete erişebilir; Admin/Manager yalnızca kendi
    şirketine. `app.domains.feedback.router._require_company_access` ile
    aynı kural, o fonksiyonun verdiğiyle aynı sebepten tekrarlanmıştır:
    kendi modülüne özeldir."""
    if current_user.role == UserRole.ROOT.value:
        return
    if (
        current_user.role in (UserRole.ADMIN.value, UserRole.MANAGER.value)
        and current_user.company_id == company_id
    ):
        return
    raise AuthorizationException(message="Bu şirketin eğitim verilerine erişim yetkiniz yok.")


@company_router.post(
    "/{company_id}/training-samples/compile",
    response_model=APIResponse[PaginatedResponse[TrainingSampleResponse]],
)
async def compile_training_samples(
    company_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Şu anda çözümlenebilir her `feedback` oyundan `training_samples`'ı
    yeniden türetir. Hiçbir şeyi eğitmez -- derlemenin neden kendi başına
    bir adım olduğu için bkz. `TrainingService.compile_samples`'ın
    docstring'i."""
    _require_company_access(current_user, company_id)
    service = _service(db)
    samples = await service.compile_samples(company_id)
    items = [TrainingSampleResponse.model_validate(s).model_dump(mode="json") for s in samples]
    await _audit_service(db).record(
        company_id=company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="training:compile",
        resource_type="training_samples",
        resource_id=company_id,
        after={"compiled_count": len(items)},
    )
    return SuccessResponse(
        data=PaginatedResponse(
            items=items, total=len(items), page=1, size=len(items) or 1, pages=1 if items else 0
        ).model_dump()
    )


@company_router.get(
    "/{company_id}/training-samples",
    response_model=APIResponse[PaginatedResponse[TrainingSampleResponse]],
)
async def list_training_samples(
    company_id: str,
    source: Optional[str] = None,
    pagination: PaginationParam = Depends(),
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Bir şirketin derlenmiş örneklerini en yeniden en eskiye listeler."""
    _require_company_access(current_user, company_id)
    service = _service(db)
    samples = await service.list_samples(
        company_id, source, skip=pagination.offset, limit=pagination.limit
    )
    total = await service.count_samples(company_id, source)
    items = [TrainingSampleResponse.model_validate(s).model_dump(mode="json") for s in samples]
    pages = (total + pagination.size - 1) // pagination.size if pagination.size else 0
    return SuccessResponse(
        data=PaginatedResponse(
            items=items, total=total, page=pagination.page, size=pagination.size, pages=pages
        ).model_dump()
    )


@company_router.get(
    "/{company_id}/training-samples/stats", response_model=APIResponse[TrainingSampleStatsResponse]
)
async def training_sample_stats(
    company_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Kaynak dağılımı + bir şirketin `MIN_FEEDBACK_SAMPLES`'a ne kadar uzak olduğu."""
    _require_company_access(current_user, company_id)
    service = _service(db)
    stats = await service.stats(company_id)
    return SuccessResponse(data=TrainingSampleStatsResponse(**stats).model_dump())


@company_router.get("/{company_id}/training-samples/export")
async def export_training_samples(
    company_id: str,
    format: str = Query(default="jsonl", pattern="^jsonl$"),
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """`.../training-runs`'ın üzerinde eğitim yaptığı aynı satırlar, indirilebilir
    JSONL olarak -- gösterilen veri ile eğitilen verinin neden aynı olduğu
    garanti edildiği için bkz. `TrainingService.export_samples`'ın docstring'i."""
    _require_company_access(current_user, company_id)
    service = _service(db)
    samples = await service.export_samples(company_id)
    lines = [
        json.dumps(
            {
                "source": s.source,
                "prompt_context": s.prompt_context,
                "chosen": s.chosen,
                "rejected": s.rejected,
                "weight": s.weight,
            },
            ensure_ascii=False,
        )
        for s in samples
    ]
    body = "\n".join(lines)
    return Response(
        content=body,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{company_id}-training-samples.jsonl"'},
    )


@router.delete("/{sample_id}", response_model=APIResponse[dict])
async def delete_training_sample(
    sample_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Bir örneği eğitim setinden kaldırır (hatalı etiket temizliği),
    çağıranın kendi şirketiyle sınırlı."""
    service = _service(db)
    sample = await service.delete_sample(sample_id, current_user.company_id)
    await _audit_service(db).record(
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="training:sample_delete",
        resource_type="training_sample",
        resource_id=sample.id,
    )
    return SuccessResponse(data={"deleted": True})


@company_router.post(
    "/{company_id}/training-runs", response_model=APIResponse[TrainingRunResponse]
)
async def trigger_training_run(
    company_id: str,
    kind: str = Query(
        default=STYLE_ADAPTER_KIND,
        pattern="^(style_adapter|lora_sft|lora_dpo)$",
        description=(
            "style_adapter (varsayılan): senkron, saniyeler içinde biter. "
            "lora_sft/lora_dpo (#191): arq üzerinden training worker'a "
            "kuyruğa alınır, saatler sürebilir -- worker çalışmıyorsa run "
            "'queued' durumunda kalır."
        ),
    ),
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Bir eğitim çalıştırmasını tetikler. `style_adapter`, yenilenmiş bir
    stil adaptörünü senkron olarak derler + çıkarır + yayınlar (bu ölçeğin
    neden bir arka plan işçisine ihtiyaç duymadığı için bkz.
    `app.domains.training.service`'in modül docstring'i). `lora_sft`/
    `lora_dpo` işi yalnızca kuyruğa alır -- fiilen çalıştırmak,
    `scripts/start_training_worker.sh` ile manuel olarak başlatılan ayrı
    bir `worker` konteynerine ihtiyaç duyar (varsayılan olarak neden
    `docker compose up`'ın bir parçası olmadığı için bkz. #191'in kendi
    gövdesi)."""
    _require_company_access(current_user, company_id)
    await _quota_service(db).check_and_increment(company_id, TRAINING_RUNS_METRIC)
    service = _service(db)
    if kind in LORA_KINDS:
        run = await service.enqueue_lora_training_run(
            company_id, kind=kind, triggered_by=current_user.id
        )
    else:
        run = await service.run_style_adapter_training(
            company_id, triggered_by=current_user.id, llm_client=get_fast_llm_client()
        )
    await _audit_service(db).record(
        company_id=company_id,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action="training:run",
        resource_type="training_run",
        resource_id=run.id,
        after={"status": run.status, "sample_count": run.sample_count},
    )
    return SuccessResponse(data=TrainingRunResponse.model_validate(run).model_dump(mode="json"))


@company_router.get(
    "/{company_id}/training-runs", response_model=APIResponse[PaginatedResponse[TrainingRunResponse]]
)
async def list_training_runs(
    company_id: str,
    pagination: PaginationParam = Depends(),
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    _require_company_access(current_user, company_id)
    service = _service(db)
    runs = await service.list_runs(company_id, skip=pagination.offset, limit=pagination.limit)
    total = await service.count_runs(company_id)
    items = [TrainingRunResponse.model_validate(r).model_dump(mode="json") for r in runs]
    pages = (total + pagination.size - 1) // pagination.size if pagination.size else 0
    return SuccessResponse(
        data=PaginatedResponse(
            items=items, total=total, page=pagination.page, size=pagination.size, pages=pages
        ).model_dump()
    )
