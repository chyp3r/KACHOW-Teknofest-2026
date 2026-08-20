import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { trainingService } from "../services/trainingService";

// companyId is optional (root's own user has none) -- every query stays
// disabled until one is known, same convention `useDocuments`'s
// `enabled: Boolean(selectedDocument)` uses for a similarly-gated query.
export function useTrainingData(companyId: string | undefined) {
  const queryClient = useQueryClient();
  const enabled = Boolean(companyId);

  const statsQuery = useQuery({
    queryKey: queryKeys.trainingStats(companyId ?? ""),
    queryFn: () => trainingService.stats(companyId!),
    enabled,
    staleTime: 30_000,
  });

  const samplesQuery = useQuery({
    queryKey: queryKeys.trainingSamples(companyId ?? ""),
    queryFn: () => trainingService.listSamples(companyId!),
    enabled,
    staleTime: 30_000,
  });

  const runsQuery = useQuery({
    queryKey: queryKeys.trainingRuns(companyId ?? ""),
    queryFn: () => trainingService.listRuns(companyId!),
    enabled,
    staleTime: 15_000,
  });

  const invalidateAll = () => {
    if (!companyId) return;
    queryClient.invalidateQueries({ queryKey: queryKeys.trainingStats(companyId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.trainingSamples(companyId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.trainingRuns(companyId) });
  };

  const compileMutation = useMutation({
    mutationFn: () => trainingService.compileSamples(companyId!),
    onSuccess: invalidateAll,
  });

  const triggerRunMutation = useMutation({
    mutationFn: () => trainingService.triggerRun(companyId!),
    onSuccess: invalidateAll,
  });

  const deleteSampleMutation = useMutation({
    mutationFn: (sampleId: string) => trainingService.deleteSample(sampleId),
    onSuccess: invalidateAll,
  });

  const exportMutation = useMutation({
    mutationFn: () => trainingService.exportSamples(companyId!),
  });

  return {
    stats: statsQuery.data,
    statsLoading: statsQuery.isLoading,
    samples: samplesQuery.data?.items ?? [],
    samplesTotal: samplesQuery.data?.total ?? 0,
    samplesLoading: samplesQuery.isLoading,
    runs: runsQuery.data?.items ?? [],
    runsLoading: runsQuery.isLoading,
    compile: () => compileMutation.mutateAsync(),
    triggerRun: () => triggerRunMutation.mutateAsync(),
    deleteSample: (sampleId: string) => deleteSampleMutation.mutateAsync(sampleId),
    exportSamples: () => exportMutation.mutateAsync(),
    isBusy:
      compileMutation.isPending || triggerRunMutation.isPending || deleteSampleMutation.isPending || exportMutation.isPending,
    error: compileMutation.error ?? triggerRunMutation.error ?? deleteSampleMutation.error ?? exportMutation.error ?? null,
  };
}
