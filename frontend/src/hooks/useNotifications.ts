import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { notificationsService } from "../services/notificationsService";

export function useNotifications() {
  const queryClient = useQueryClient();

  const listQuery = useQuery({
    queryKey: queryKeys.notifications(false),
    queryFn: () => notificationsService.list(false, 1, 20),
    staleTime: 15_000,
  });

  // `total` on an `unread_only=true, size=1` page is the cheapest way to
  // read just the unread count -- same trick `GET /notifications`'s own
  // pagination envelope already supports, no dedicated count endpoint
  // needed on the backend.
  const unreadCountQuery = useQuery({
    queryKey: queryKeys.notifications(true),
    queryFn: () => notificationsService.list(true, 1, 1),
    staleTime: 10_000,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["notifications"] });
  };

  const markReadMutation = useMutation({
    mutationFn: (notificationId: string) => notificationsService.markRead(notificationId),
    onSuccess: invalidate,
  });

  const markAllReadMutation = useMutation({
    mutationFn: () => notificationsService.markAllRead(),
    onSuccess: invalidate,
  });

  return {
    notifications: listQuery.data?.items ?? [],
    unreadCount: unreadCountQuery.data?.total ?? 0,
    loading: listQuery.isLoading,
    error: listQuery.error instanceof Error ? listQuery.error.message : null,
    markRead: (notificationId: string) => markReadMutation.mutateAsync(notificationId),
    markAllRead: () => markAllReadMutation.mutateAsync(),
    markingAllRead: markAllReadMutation.isPending,
    invalidate,
  };
}
