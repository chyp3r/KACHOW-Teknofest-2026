import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { poolService } from "../services/poolService";

export function usePersonalPool(enabled = true) {
  const queryClient = useQueryClient();
  const pool = useQuery({ queryKey: queryKeys.personalPool, queryFn: poolService.mine, enabled });
  const items = useQuery({
    queryKey: queryKeys.poolItems(pool.data?.id ?? ""),
    queryFn: () => poolService.items(pool.data!.id),
    enabled: enabled && Boolean(pool.data?.id),
  });
  const refresh = () => {
    if (pool.data?.id) void queryClient.invalidateQueries({ queryKey: queryKeys.poolItems(pool.data.id) });
  };
  const acknowledge = useMutation({ mutationFn: poolService.acknowledge, onSuccess: refresh });
  const adopt = useMutation({
    mutationFn: poolService.adopt,
    onSuccess: () => { refresh(); void queryClient.invalidateQueries({ queryKey: ["documents"] }); },
  });
  const remove = useMutation({
    mutationFn: (itemId: string) => poolService.remove(pool.data!.id, itemId),
    onSuccess: refresh,
  });
  return {
    pool: pool.data, items: items.data?.items ?? [], total: items.data?.total ?? 0,
    loading: pool.isLoading || items.isLoading, error: pool.error ?? items.error ?? acknowledge.error ?? adopt.error ?? remove.error,
    busy: acknowledge.isPending || adopt.isPending || remove.isPending,
    acknowledge: acknowledge.mutateAsync, adopt: adopt.mutateAsync, remove: remove.mutateAsync,
  };
}
