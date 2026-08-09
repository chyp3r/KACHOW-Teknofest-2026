import { useMutation } from "@tanstack/react-query";
import { routingService } from "../services/routingService";

export function useRoutingSuggestion() {
  const mutation = useMutation({ mutationFn: routingService.suggest });
  return {
    suggestion: mutation.data ?? null,
    loading: mutation.isPending,
    error: mutation.error instanceof Error ? mutation.error.message : null,
    errorObject: mutation.error,
    suggest: mutation.mutateAsync,
    reset: mutation.reset,
  };
}
