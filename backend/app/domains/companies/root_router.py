"""Root konsolu -- sistem geneli okumalar, hiçbir zaman tek bir şirkete
kapsamlanmaz (bu repository'nin şirkete özel `AnalyticsRepository`'den
neden ayrı olduğu için `app.domains.companies.root_repository`'nin kendi
modül docstring'ine bakın). Buradaki her rota yalnızca Root'a özeldir.
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import require_roles
from app.api.responses import APIResponse, SuccessResponse
from app.core.enums.user_role import UserRole
from app.domains.companies.root_repository import RootRepository
from app.domains.users.model.user_model import UserModel
from app.infrastructure.database.session import get_db
from app.observability.prometheus_query import llm_token_usage

router = APIRouter(prefix="/root", tags=["root"])


@router.get("/overview", response_model=APIResponse[dict])
async def root_overview(
    current_user: UserModel = Depends(require_roles(UserRole.ROOT)),
    db: AsyncSession = Depends(get_db),
):
    """Sistem geneli sayılar: tüm şirketler genelinde bir arada şirketler,
    kullanıcılar, belgeler, taslaklar ve çalışma durumu/hata oranı dökümü."""
    repository = RootRepository(db)
    total_companies = await repository.total_companies()
    total_users = await repository.total_users()
    total_documents = await repository.total_documents()
    total_drafts = await repository.total_drafts()
    run_status = dict(await repository.run_status_totals())
    total_runs = sum(run_status.values())
    failed_runs = run_status.get("failed", 0)
    error_rate = (failed_runs / total_runs) if total_runs else 0.0

    return SuccessResponse(
        data={
            "total_companies": total_companies,
            "total_users": total_users,
            "total_documents": total_documents,
            "total_drafts": total_drafts,
            "run_status": run_status,
            "total_runs": total_runs,
            "error_rate": error_rate,
        }
    )


@router.get("/companies/stats", response_model=APIResponse[list])
async def root_company_stats(
    current_user: UserModel = Depends(require_roles(UserRole.ROOT)),
    db: AsyncSession = Depends(get_db),
):
    """Şirket başına toplu bakış: kimlik bilgisi artı kullanıcı/belge/taslak sayıları."""
    repository = RootRepository(db)
    return SuccessResponse(data=await repository.company_rollup())


@router.get("/users/stats", response_model=APIResponse[dict])
async def root_user_stats(
    current_user: UserModel = Depends(require_roles(UserRole.ROOT)),
    db: AsyncSession = Depends(get_db),
):
    """Sistem geneli rol dökümü ve 7 günlük aktif kullanıcı sayısı --
    burada "aktif" olmanın ne anlama geldiği için (izlenen bir giriş
    zaman damgası değil, bir `runs` satırı)
    `app.domains.analytics.repository.AnalyticsRepository.active_user_count`'un
    docstring'ine bakın."""
    repository = RootRepository(db)
    by_role = dict(await repository.users_by_role())
    active_7d = await repository.active_user_count(days=7)
    active_30d = await repository.active_user_count(days=30)
    per_company = await repository.company_rollup()
    return SuccessResponse(
        data={
            "by_role": by_role,
            "active_7d": active_7d,
            "active_30d": active_30d,
            "seats_by_company": [
                {"company_id": row["company_id"], "name": row["name"], "user_count": row["user_count"]}
                for row in per_company
            ],
        }
    )


@router.get("/users/insights", response_model=APIResponse[dict])
async def root_user_insights(
    current_user: UserModel = Depends(require_roles(UserRole.ROOT)),
    db: AsyncSession = Depends(get_db),
):
    """"Kullanıcı İstatistikleri" konsolunu besleyen zengin sistem-geneli
    döküm: KPI'lar, günlük aktiflik zaman serisi, rol dağılımı, kurum
    koltukları, en aktif kullanıcılar, iş akışı türü/sonuç dağılımı,
    guardrail sinyalleri ve Prometheus'tan global AI token kullanımı.

    "Aktif" burada da izlenen bir giriş zaman damgası değil, bir ``runs``
    satırı demektir (bkz. ``root_user_stats``).
    """
    repository = RootRepository(db)

    by_role = dict(await repository.users_by_role())
    total_users = sum(by_role.values())
    active_7d = await repository.active_user_count(days=7)
    active_30d = await repository.active_user_count(days=30)
    new_7d = await repository.new_user_count(days=7)
    new_30d = await repository.new_user_count(days=30)
    run_status = dict(await repository.run_status_totals())
    total_runs = sum(run_status.values())
    per_company = await repository.company_rollup()

    return SuccessResponse(
        data={
            "kpis": {
                "total_users": total_users,
                "active_7d": active_7d,
                "active_30d": active_30d,
                "activity_rate_30d": (active_30d / total_users) if total_users else 0.0,
                "new_7d": new_7d,
                "new_30d": new_30d,
                "total_runs": total_runs,
                "runs_per_active_user_30d": (total_runs / active_30d) if active_30d else 0.0,
            },
            "daily_activity": await repository.daily_activity(days=30),
            "by_role": by_role,
            "seats_by_company": [
                {
                    "company_id": row["company_id"],
                    "name": row["name"],
                    "user_count": row["user_count"],
                    "is_active": row["is_active"],
                }
                for row in per_company
            ],
            "top_users": await repository.top_users(limit=15),
            "runs_by_intent": dict(await repository.runs_by_intent()),
            "runs_by_status": run_status,
            "guardrail_by_decision": dict(await repository.guardrail_by_decision()),
            "token_usage": await llm_token_usage(),
        }
    )


@router.get("/health", response_model=APIResponse[dict])
async def root_health(
    response: Response,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT)),
    db: AsyncSession = Depends(get_db),
):
    """`GET /health?deep=true`'nin tam bağımlılık kontrolü, artı şirket
    başına son etkinlik görünümü (root'a özgü "hangi kiracı bayat
    görünüyor" sorusu -- düz sağlık kontrolünün yanıtlayacağı bir kiracı
    kavramı yoktur)."""
    from app.domains.system.router import build_health_payload

    data, degraded = await build_health_payload(deep=True)
    if degraded:
        response.status_code = 503

    repository = RootRepository(db)
    last_activity = await repository.last_activity_by_company()
    data["companies_last_activity"] = {
        company_id: last_seen.isoformat() if last_seen is not None else None
        for company_id, last_seen in last_activity.items()
    }
    return SuccessResponse(data=data)
