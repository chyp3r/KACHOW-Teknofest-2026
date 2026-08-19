import { apiRequest } from "./apiClient";
import type {
  AnalyticsLinks,
  AnalyticsSummary,
  GuardrailBreakdown,
  TimeseriesPoint,
  UnitVolume,
} from "../types/management";

const companyPath = (companyId: string) =>
  `/api/v1/companies/${encodeURIComponent(companyId)}/analytics`;

export const analyticsService = {
  summary: (companyId: string) =>
    apiRequest<AnalyticsSummary>(`${companyPath(companyId)}/summary`),
  timeseries: (companyId: string, metric: string, days: number) => {
    const dateFrom = new Date(Date.now() - days * 86_400_000).toISOString();
    const params = new URLSearchParams({ metric, date_from: dateFrom, bucket: days > 31 ? "week" : "day" });
    return apiRequest<TimeseriesPoint[]>(`${companyPath(companyId)}/timeseries?${params}`);
  },
  units: (companyId: string) => apiRequest<UnitVolume[]>(`${companyPath(companyId)}/units`),
  guardrails: (companyId: string) =>
    apiRequest<GuardrailBreakdown[]>(`${companyPath(companyId)}/guardrails`),
  links: (companyId: string) => apiRequest<AnalyticsLinks>(`${companyPath(companyId)}/links`),
};
