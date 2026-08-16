import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { notificationsService } from "../services/notificationsService";
import { subscribeToRawStream } from "../services/sse";

/**
 * Live-updates the notification bell via `GET /notifications/stream` --
 * the endpoint has existed since the draft-sharing work but had no
 * frontend consumer until now (see the plan's own gap analysis). A push
 * only ever triggers a refetch, never writes the payload directly into the
 * cache: `NotificationResponse`'s shape here is exactly what
 * `useNotifications`'s two list queries already fetch, so there is no
 * separate cache shape to reconcile it against.
 */
export function useNotificationsStream(enabled: boolean): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled) return undefined;
    const unsubscribe = subscribeToRawStream(notificationsService.streamPath, () => {
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    });
    return unsubscribe;
  }, [enabled, queryClient]);
}
