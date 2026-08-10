import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { healthService } from "../services/healthService";

export function useHealth() {
  const normal = useQuery({
    queryKey: queryKeys.health(false),
    queryFn: () => healthService.get(false),
    staleTime: 30_000,
  });
  const deep = useQuery({
    queryKey: queryKeys.health(true),
    queryFn: () => healthService.get(true),
    enabled: false,
    retry: false,
  });
  return {
    status: deep.data ?? normal.data ?? null,
    loading: normal.isLoading,
    deepLoading: deep.isFetching,
    error:
      deep.error instanceof Error
        ? deep.error.message
        : normal.error instanceof Error
          ? normal.error.message
          : null,
    errorObject: deep.error ?? normal.error,
    runDeep: deep.refetch,
    refresh: normal.refetch,
  };
}
