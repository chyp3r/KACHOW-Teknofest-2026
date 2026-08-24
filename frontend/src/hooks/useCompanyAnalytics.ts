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
  const runsTimeseries = useQuery({
    queryKey: queryKeys.analyticsTimeseries(companyId ?? "", "runs", days),
    queryFn: () => analyticsService.timeseries(companyId!, "runs", days),
    enabled: canLoad,
    staleTime: 60_000,
  });
  const guardrailTimeseries = useQuery({
    queryKey: queryKeys.analyticsTimeseries(companyId ?? "", "guardrail_blocks", days),
    queryFn: () => analyticsService.timeseries(companyId!, "guardrail_blocks", days),
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
    runTimeseries: runsTimeseries.data ?? [],
    guardrailTimeseries: guardrailTimeseries.data ?? [],
    units: units.data ?? [],
    loading: summary.isLoading || documentsTimeseries.isLoading || draftsTimeseries.isLoading || runsTimeseries.isLoading || guardrailTimeseries.isLoading || units.isLoading,
    error: summary.error ?? documentsTimeseries.error ?? draftsTimeseries.error ?? runsTimeseries.error ?? guardrailTimeseries.error ?? units.error,
  };
}
