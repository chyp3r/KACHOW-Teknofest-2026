import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { documentService } from "../services/documentService";

export function useDraftCreation() {
  const queryClient = useQueryClient();
  const types = useQuery({
    queryKey: ["correspondence-types"],
    queryFn: documentService.correspondenceTypes,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const create = useMutation({
    mutationFn: documentService.createDraft,
    onSuccess: (draft) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.drafts() });
      if (draft.draft_id) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.draft(draft.draft_id) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.draftVersions(draft.draft_id) });
      }
    },
  });
  return {
    correspondenceTypes: types.data ?? [],
    typesLoading: types.isLoading,
    draft: create.data ?? null,
    creating: create.isPending,
    error: create.error instanceof Error ? create.error.message : null,
    errorObject: create.error,
    create: create.mutateAsync,
    reset: create.reset,
  };
}
