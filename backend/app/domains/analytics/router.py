from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import require_roles
from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.validation import ValidationException
from app.api.responses import APIResponse, SuccessResponse
from app.core.config import settings
from app.core.enums.user_role import UserRole
from app.domains.analytics.repository import AnalyticsRepository
from app.domains.analytics.schema import AnalyticsLinksResponse, AnalyticsSummaryResponse
from app.domains.analytics.service import AnalyticsService
from app.domains.companies.repository import CompanyRepository
from app.domains.quotas.repository import CompanyQuotaRepository, UsageCounterRepository
from app.domains.quotas.service import QuotaService
from app.domains.users.model.user_model import UserModel
from app.infrastructure.cache import get_cache
from app.infrastructure.database.session import get_db

router = APIRouter(prefix="/companies", tags=["analytics"])


def _require_company_access(current_user: UserModel, company_id: str) -> None:
    """Root reaches any company; Admin/Manager only their own.

    Same rule `app.domains.companies.router._require_company_access`
    enforces for company records themselves -- duplicated rather than
    imported since that helper is private to its own module and this is a
    one-line check, not worth a shared-utility module for.
    """
    if current_user.role == UserRole.ROOT.value:
        return
    if current_user.role in (UserRole.ADMIN.value, UserRole.MANAGER.value) and current_user.company_id == company_id:
        return
    raise AuthorizationException(message="Bu şirketin analitiklerine erişim yetkiniz yok.")


def _analytics_service(db: AsyncSession) -> AnalyticsService:
    return AnalyticsService(
        repository=AnalyticsRepository(db),
        cache=get_cache(),
        quota_service=QuotaService(UsageCounterRepository(db), CompanyQuotaRepository(db)),
    )


@router.get("/{company_id}/analytics/summary", response_model=APIResponse[AnalyticsSummaryResponse])
async def analytics_summary(
    company_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Document/draft/run/guardrail volume + quota usage for one company."""
    _require_company_access(current_user, company_id)
    service = _analytics_service(db)
    summary = await service.summary(company_id)
    return SuccessResponse(data=summary)


@router.get("/{company_id}/analytics/timeseries", response_model=APIResponse[list])
async def analytics_timeseries(
    company_id: str,
    metric: str = Query(..., description="'documents' | 'drafts' | 'runs' | 'guardrail_blocks'"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    bucket: str = Query(default="day", description="'day' | 'week'"),
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """One metric's volume over time, bucketed by day or week."""
    _require_company_access(current_user, company_id)
    service = _analytics_service(db)
    try:
        points = await service.timeseries(company_id, metric, date_from, date_to, bucket)
    except ValueError as exc:
        raise ValidationException(message=str(exc)) from exc
    return SuccessResponse(data=points)


@router.get("/{company_id}/analytics/units", response_model=APIResponse[list])
async def analytics_units(
    company_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Draft volume per routed unit (`drafts.destination`)."""
    _require_company_access(current_user, company_id)
    service = _analytics_service(db)
    return SuccessResponse(data=await service.units(company_id))


@router.get("/{company_id}/analytics/guardrails", response_model=APIResponse[list])
async def analytics_guardrails(
    company_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
):
    """Guardrail decision breakdown by stage/kind/decision."""
    _require_company_access(current_user, company_id)
    service = _analytics_service(db)
    return SuccessResponse(data=await service.guardrails(company_id))


@router.get("/{company_id}/analytics/links", response_model=APIResponse[AnalyticsLinksResponse])
async def analytics_links(
    company_id: str,
    current_user: UserModel = Depends(require_roles(UserRole.ROOT, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Grafana/Langfuse deep links, pre-filtered to this company where the
    target tool supports it (Grafana's `company` template variable --
    Langfuse's own tagging is honest-but-unverified, see
    `app.observability.tracer.build_trace_config`'s docstring)."""
    _require_company_access(current_user, company_id)
    company = await CompanyRepository(db).get_by_id(company_id)
    if company is None:
        from app.api.exceptions.not_found import NotFoundException

        raise NotFoundException(message="Şirket bulunamadı.")
    grafana_url = (
        f"{settings.GRAFANA_URL}/d/kachow-company-metrics"
        f"?var-company={company.slug}"
    )
    langfuse_url = f"{settings.LANGFUSE_PUBLIC_URL}?tag=company:{company.slug}"
    return SuccessResponse(data=AnalyticsLinksResponse(grafana_url=grafana_url, langfuse_url=langfuse_url))
