import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { analyticsService } from "../services/analyticsService";

export function useCompanyAnalytics(companyId: string | undefined, days = 7, enabled = true) {
  const canLoad = Boolean(companyId) && enabled;
  const summary = useQuery({
    queryKey: queryKeys.analyticsSummary(companyId ?? ""),
    queryFn: () => analyticsService.summary(companyId!),
    enabled: canLoad,
    staleTime: 60_000,
  });
  const documentsTimeseries = useQuery({
    queryKey: queryKeys.analyticsTimeseries(companyId ?? "", "documents", days),
    queryFn: () => analyticsService.timeseries(companyId!, "documents", days),
    enabled: canLoad,
    staleTime: 60_000,
  });
  const draftsTimeseries = useQuery({
    queryKey: queryKeys.analyticsTimeseries(companyId ?? "", "drafts", days),
    queryFn: () => analyticsService.timeseries(companyId!, "drafts", days),
    enabled: canLoad,
    staleTime: 60_000,
  });
  const units = useQuery({
    queryKey: queryKeys.analyticsUnits(companyId ?? ""),
    queryFn: () => analyticsService.units(companyId!),
    enabled: canLoad,
    staleTime: 60_000,
  });
  return {
    summary: summary.data,
    documentTimeseries: documentsTimeseries.data ?? [],
    draftTimeseries: draftsTimeseries.data ?? [],
    units: units.data ?? [],
    loading: summary.isLoading || documentsTimeseries.isLoading || draftsTimeseries.isLoading || units.isLoading,
    error: summary.error ?? documentsTimeseries.error ?? draftsTimeseries.error ?? units.error,
  };
}
