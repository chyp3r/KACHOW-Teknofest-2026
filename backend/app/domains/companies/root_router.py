"""The root console -- system-wide reads, never scoped to a single company
(see `app.domains.companies.root_repository`'s own module docstring for why
that repository is separate from the per-company `AnalyticsRepository`).
Every route here is Root-only.
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import require_roles
from app.api.responses import APIResponse, SuccessResponse
from app.core.enums.user_role import UserRole
from app.domains.companies.root_repository import RootRepository
from app.domains.users.model.user_model import UserModel
from app.infrastructure.database.session import get_db

router = APIRouter(prefix="/root", tags=["root"])


@router.get("/overview", response_model=APIResponse[dict])
async def root_overview(
    current_user: UserModel = Depends(require_roles(UserRole.ROOT)),
    db: AsyncSession = Depends(get_db),
):
    """System-wide counts: companies, users, documents, drafts, and run
    status/error-rate breakdown, across every company at once."""
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
    """Per-company rollup: identity plus user/document/draft counts."""
    repository = RootRepository(db)
    return SuccessResponse(data=await repository.company_rollup())


@router.get("/users/stats", response_model=APIResponse[dict])
async def root_user_stats(
    current_user: UserModel = Depends(require_roles(UserRole.ROOT)),
    db: AsyncSession = Depends(get_db),
):
    """Role breakdown and 7-day active count, system-wide -- see
    `app.domains.analytics.repository.AnalyticsRepository.active_user_count`'s
    docstring for what "active" means here (a `runs` row, not a tracked
    login timestamp)."""
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


@router.get("/health", response_model=APIResponse[dict])
async def root_health(
    response: Response,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT)),
    db: AsyncSession = Depends(get_db),
):
    """`GET /health?deep=true`'s full dependency probe, plus a per-company
    last-activity view (root's own "which tenant looks stale" question,
    which the plain health check has no concept of a tenant to answer)."""
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
