import { apiRequest } from "./apiClient";
import type { User, UserRole } from "../types/users";
import type { SensitivityLevel } from "../types/security";
import type { PaginatedResponse } from "../types/api";
import type { UserSearchResult } from "../types/favorites";
import type { PermissionGrant, PermissionGrantInput } from "../types/management";

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
  get: (id: string) => apiRequest<User>(`/api/v1/users/${encodeURIComponent(id)}`),
  // Unauthenticated -- the registrant has no token yet (mirrors
  // authService.login's own POST /api/v1/auth/login call). The backend
  // ignores any role/company in the body and derives both from the
  // caller's invite (see UserService.register_user's own docstring), so
  // this deliberately never accepts a role parameter.
  register: (username: string, email: string, password: string) =>
    apiRequest<User>("/api/v1/users", {
      method: "POST",
      body: JSON.stringify({ username, email, password }),
    }, { authenticated: false }),
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
  permissions: (userId: string) =>
    apiRequest<PermissionGrant[]>(`/api/v1/users/${encodeURIComponent(userId)}/permissions`),
  grantPermission: (userId: string, input: PermissionGrantInput) =>
    apiRequest<PermissionGrant>(`/api/v1/users/${encodeURIComponent(userId)}/permissions`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  revokePermission: (grantId: string) =>
    apiRequest<null>(`/api/v1/users/permissions/${encodeURIComponent(grantId)}`, { method: "DELETE" }),
};
