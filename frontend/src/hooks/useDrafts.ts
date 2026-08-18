import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { draftService } from "../services/draftService";
import type { PaginatedResponse } from "../types/api";
import type { PersistedDraft } from "../types/drafts";

export function useDrafts(activeDraftId?: string) {
  const queryClient = useQueryClient();
  const listQuery = useQuery({
    queryKey: queryKeys.drafts(),
    queryFn: () => draftService.list(),
    staleTime: 20_000,
  });
  const detailQuery = useQuery({
    queryKey: queryKeys.draft(activeDraftId ?? ""),
    queryFn: () => draftService.get(activeDraftId!),
    enabled: Boolean(activeDraftId),
  });
  const versionsQuery = useQuery({
    queryKey: queryKeys.draftVersions(activeDraftId ?? ""),
    queryFn: () => draftService.versions(activeDraftId!),
    enabled: Boolean(activeDraftId),
  });

  const registerCreatedDraft = (created: PersistedDraft) => {
    queryClient.setQueryData(queryKeys.draft(created.id), created);
    void queryClient.invalidateQueries({ queryKey: ["drafts"] });
  };
  const removeMutation = useMutation({
    mutationFn: (draftId: string) => draftService.remove(draftId),
    onSuccess: (_result, draftId) => {
      queryClient.setQueryData<PaginatedResponse<PersistedDraft>>(
        queryKeys.drafts(),
        (current) =>
          current
            ? {
                ...current,
                items: current.items.filter((item) => item.id !== draftId),
                total: Math.max(0, current.total - 1),
              }
            : current,
      );
      void queryClient.invalidateQueries({ queryKey: ["drafts"] });
    },
  });
  const updateDestinationMutation = useMutation({
    mutationFn: ({ draftId, destination }: { draftId: string; destination: string }) =>
      draftService.updateDestination(draftId, destination),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.draft(updated.id), updated);
      queryClient.setQueryData<PaginatedResponse<PersistedDraft>>(
        queryKeys.drafts(),
        (current) =>
          current
            ? {
                ...current,
                items: current.items.map((item) => (item.id === updated.id ? updated : item)),
              }
            : current,
      );
    },
  });
  const errorObject = listQuery.error ?? detailQuery.error ?? versionsQuery.error;

  return {
    drafts: listQuery.data?.items ?? [],
    total: listQuery.data?.total ?? 0,
    activeDraft: detailQuery.data ?? null,
    versions: versionsQuery.data ?? [],
    loading: listQuery.isLoading,
    detailLoading: detailQuery.isLoading || versionsQuery.isLoading,
    refreshing: listQuery.isFetching && !listQuery.isLoading,
    error:
      listQuery.error instanceof Error
        ? listQuery.error.message
        : detailQuery.error instanceof Error
          ? detailQuery.error.message
          : versionsQuery.error instanceof Error
            ? versionsQuery.error.message
            : null,
    errorObject,
    refresh: () => listQuery.refetch(),
    registerCreatedDraft,
    deleting: removeMutation.isPending,
    deleteDraft: async (draftId: string) => {
      await removeMutation.mutateAsync(draftId);
    },
    updatingDestination: updateDestinationMutation.isPending,
    updateDestination: async (draftId: string, destination: string) => {
      await updateDestinationMutation.mutateAsync({ draftId, destination });
    },
  };
}
