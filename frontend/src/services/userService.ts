import { apiRequest } from "./apiClient";
import type { User, UserRole } from "../types/users";
import type { SensitivityLevel } from "../types/security";

export const userService = {
  list: () => apiRequest<User[]>("/api/v1/users"),
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
