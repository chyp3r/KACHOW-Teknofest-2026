from typing import List, Optional

from pydantic import BaseModel


class UsageSummary(BaseModel):
    period: str
    used: int
    limit: Optional[int] = None


class DraftStats(BaseModel):
    total: int
    avg_confidence_score: Optional[float] = None
    requires_human_approval: int


class AnalyticsSummaryResponse(BaseModel):
    company_id: str
    document_count: int
    draft_stats: DraftStats
    run_status: dict[str, int]
    active_users_7d: int
    guardrail_blocked_total: int
    usage: dict[str, UsageSummary]


class TimeseriesPoint(BaseModel):
    bucket: str
    count: int


class UnitVolumeItem(BaseModel):
    destination: Optional[str] = None
    unit_id: Optional[str] = None
    count: int


class GuardrailBreakdownItem(BaseModel):
    stage: str
    kind: str
    decision: str
    count: int


class AnalyticsLinksResponse(BaseModel):
    grafana_url: str
    langfuse_url: str
