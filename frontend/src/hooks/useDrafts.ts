import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { draftService } from "../services/draftService";
import type { PaginatedResponse } from "../types/api";
import type { PersistedDraft } from "../types/drafts";

export function useDrafts(activeDraftId?: string, includeShares = false) {
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
  const inboxQuery = useQuery({
    queryKey: queryKeys.draftInbox,
    queryFn: draftService.inbox,
    staleTime: 20_000,
    enabled: includeShares,
  });
  const outboxQuery = useQuery({
    queryKey: queryKeys.draftOutbox,
    queryFn: draftService.outbox,
    staleTime: 20_000,
    enabled: includeShares,
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
  const approveReviewMutation = useMutation({
    mutationFn: (draftId: string) => draftService.approveReview(draftId),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.draft(updated.id), updated);
      queryClient.setQueryData<PersistedDraft[]>(
        queryKeys.draftVersions(updated.id),
        (current) => current?.map((item) => (item.id === updated.id ? updated : item)),
      );
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
  const sendMutation = useMutation({
    mutationFn: ({ draftId, recipientIds, message }: { draftId: string; recipientIds: string[]; message?: string }) =>
      draftService.send(draftId, recipientIds, message),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.draftOutbox }),
  });
  const respondMutation = useMutation({
    mutationFn: ({ shareId, action }: { shareId: string; action: "accept" | "reject" }) =>
      draftService.respond(shareId, action),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.draftInbox });
      void queryClient.invalidateQueries({ queryKey: ["drafts"] });
    },
  });
  const readShareMutation = useMutation({
    mutationFn: draftService.markShareRead,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.draftInbox }),
  });
  const revokeShareMutation = useMutation({
    mutationFn: draftService.revokeShare,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.draftOutbox }),
  });
  const errorObject =
    listQuery.error
    ?? detailQuery.error
    ?? versionsQuery.error
    ?? inboxQuery.error
    ?? outboxQuery.error
    ?? approveReviewMutation.error;

  return {
    drafts: listQuery.data?.items ?? [],
    total: listQuery.data?.total ?? 0,
    inbox: inboxQuery.data?.items ?? [],
    inboxTotal: inboxQuery.data?.total ?? 0,
    outbox: outboxQuery.data?.items ?? [],
    outboxTotal: outboxQuery.data?.total ?? 0,
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
            : approveReviewMutation.error instanceof Error
              ? approveReviewMutation.error.message
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
    approvingReview: approveReviewMutation.isPending,
    approveReview: async (draftId: string) => {
      await approveReviewMutation.mutateAsync(draftId);
    },
    sending: sendMutation.isPending,
    sendDraft: async (draftId: string, recipientIds: string[], message?: string) => {
      await sendMutation.mutateAsync({ draftId, recipientIds, message });
    },
    responding: respondMutation.isPending,
    respondToShare: async (shareId: string, action: "accept" | "reject") => {
      await respondMutation.mutateAsync({ shareId, action });
    },
    markingShareRead: readShareMutation.isPending,
    markShareRead: (shareId: string) => readShareMutation.mutateAsync(shareId),
    revokingShare: revokeShareMutation.isPending,
    revokeShare: (shareId: string) => revokeShareMutation.mutateAsync(shareId),
  };
}
