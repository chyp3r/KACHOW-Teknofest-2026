import { apiRequest } from "./apiClient";
import type { Favorite } from "../types/favorites";

export const favoritesService = {
  list: () => apiRequest<Favorite[]>("/api/v1/users/me/favorites"),
  add: (userId: string, note?: string) =>
    apiRequest<Favorite>("/api/v1/users/me/favorites", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, note: note ?? null }),
    }),
  remove: (userId: string) =>
    apiRequest<{ removed: boolean }>(
      `/api/v1/users/me/favorites/${encodeURIComponent(userId)}`,
      { method: "DELETE" },
    ),
};
