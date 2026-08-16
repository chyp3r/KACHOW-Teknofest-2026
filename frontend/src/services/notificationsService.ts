import { apiRequest } from "./apiClient";
import type { PaginatedResponse } from "../types/api";
import type { Notification } from "../types/notifications";

export const notificationsService = {
  list: (unreadOnly = false, page = 1, size = 20) =>
    apiRequest<PaginatedResponse<Notification>>(
      `/api/v1/notifications?unread_only=${unreadOnly}&page=${page}&size=${size}`,
    ),
  markRead: (notificationId: string) =>
    apiRequest<Notification>(
      `/api/v1/notifications/${encodeURIComponent(notificationId)}/read`,
      { method: "POST" },
    ),
  markAllRead: () =>
    apiRequest<{ marked_read: number }>("/api/v1/notifications/read-all", {
      method: "POST",
    }),
  streamPath: "/api/v1/notifications/stream",
};
