import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { favoritesService } from "../services/favoritesService";
import type { Favorite } from "../types/favorites";

export function useFavorites() {
  const queryClient = useQueryClient();
  const listQuery = useQuery({
    queryKey: queryKeys.favorites,
    queryFn: () => favoritesService.list(),
    staleTime: 30_000,
  });

  const addMutation = useMutation({
    mutationFn: ({ userId, note }: { userId: string; note?: string }) =>
      favoritesService.add(userId, note),
    onSuccess: (favorite) => {
      queryClient.setQueryData<Favorite[]>(queryKeys.favorites, (current = []) => [
        favorite,
        ...current.filter((item) => item.favorite_user_id !== favorite.favorite_user_id),
      ]);
    },
  });

  const removeMutation = useMutation({
    mutationFn: (userId: string) => favoritesService.remove(userId),
    onSuccess: (_result, userId) => {
      queryClient.setQueryData<Favorite[]>(queryKeys.favorites, (current = []) =>
        current.filter((item) => item.favorite_user_id !== userId),
      );
    },
  });

  const favoriteIds = new Set((listQuery.data ?? []).map((item) => item.favorite_user_id));

  return {
    favorites: listQuery.data ?? [],
    favoriteIds,
    loading: listQuery.isLoading,
    error: listQuery.error instanceof Error ? listQuery.error.message : null,
    errorObject: listQuery.error ?? addMutation.error ?? removeMutation.error,
    add: (userId: string, note?: string) => addMutation.mutateAsync({ userId, note }),
    adding: addMutation.isPending,
    remove: (userId: string) => removeMutation.mutateAsync(userId),
    removing: removeMutation.isPending,
  };
}
