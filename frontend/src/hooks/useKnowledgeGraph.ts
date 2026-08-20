import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { graphService } from "../services/graphService";

export function useKnowledgeGraph() {
  const query = useQuery({
    queryKey: queryKeys.knowledgeGraph,
    queryFn: () => graphService.corpusGraph(),
    staleTime: 60_000,
  });
  return {
    graph: query.data ?? null,
    loading: query.isLoading,
    refreshing: query.isFetching && !query.isLoading,
    error: query.error instanceof Error ? query.error.message : null,
    refresh: async () => {
      await query.refetch();
    },
  };
}
