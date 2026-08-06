import { apiRequest } from "./apiClient";
import type { User, UserRole } from "../types/users";

export const userService = {
  list: () => apiRequest<User[]>("/api/v1/users"),
  invite: (email: string, role: UserRole) =>
    apiRequest("/api/v1/users/invitations", {
      method: "POST",
      body: JSON.stringify({ email, role }),
    }),
  update: (id: string, changes: { role?: UserRole; is_active?: boolean }) =>
    apiRequest<User>(`/api/v1/users/${id}`, {
      method: "PUT",
      body: JSON.stringify(changes),
    }),
  removeAccess: (id: string) =>
    apiRequest<null>(`/api/v1/users/${id}/soft`, { method: "DELETE" }),
};
