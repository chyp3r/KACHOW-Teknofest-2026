import { apiRequest } from "./apiClient";
import type { User, UserRole } from "../types/users";
import type { SensitivityLevel } from "../types/security";
import type { PaginatedResponse } from "../types/api";
import type { UserSearchResult } from "../types/favorites";

export interface UserSearchFilters {
  q?: string;
  unitId?: string;
  role?: UserRole;
}

export const userService = {
  list: () => apiRequest<User[]>("/api/v1/users"),
  search: (filters: UserSearchFilters, page = 1, size = 20) => {
    const params = new URLSearchParams({ page: String(page), size: String(size) });
    if (filters.q) params.set("q", filters.q);
    if (filters.unitId) params.set("unit_id", filters.unitId);
    if (filters.role) params.set("role", filters.role);
    return apiRequest<PaginatedResponse<UserSearchResult>>(
      `/api/v1/users/search?${params.toString()}`,
    );
  },
  invite: (email: string, role: UserRole) =>
    apiRequest("/api/v1/users/invitations", {
      method: "POST",
      body: JSON.stringify({ email, role }),
    }),
  update: (
    id: string,
    changes: {
      email?: string;
      role?: UserRole;
      is_active?: boolean;
      clearance_level?: SensitivityLevel;
    },
  ) =>
    apiRequest<User>(`/api/v1/users/${id}`, {
      method: "PUT",
      body: JSON.stringify(changes),
    }),
  removeAccess: (id: string) =>
    apiRequest<null>(`/api/v1/users/${id}/soft`, { method: "DELETE" }),
  deletePermanently: (id: string) =>
    apiRequest<null>(`/api/v1/users/${id}/hard`, { method: "DELETE" }),
  changePassword: (currentPassword: string, newPassword: string) =>
    apiRequest<null>("/api/v1/users/me/password", {
      method: "POST",
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    }),
};
