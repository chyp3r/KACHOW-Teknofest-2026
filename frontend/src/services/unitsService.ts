import { apiRequest } from "./apiClient";
import type { Unit, UnitMember } from "../types/units";

export const unitsService = {
  list: () => apiRequest<Unit[]>("/api/v1/units"),
  create: (input: Pick<Unit, "name" | "description">) =>
    apiRequest<Unit>("/api/v1/units", { method: "POST", body: JSON.stringify(input) }),
  update: (unitId: string, input: Partial<Pick<Unit, "name" | "description" | "is_active">>) =>
    apiRequest<Unit>(`/api/v1/units/${encodeURIComponent(unitId)}`, { method: "PATCH", body: JSON.stringify(input) }),
  remove: (unitId: string) =>
    apiRequest<null>(`/api/v1/units/${encodeURIComponent(unitId)}`, { method: "DELETE" }),
  members: (unitId: string) =>
    apiRequest<UnitMember[]>(`/api/v1/units/${encodeURIComponent(unitId)}/members`),
  addMember: (unitId: string, input: { user_id: string; is_primary?: boolean; role_in_unit?: string | null }) =>
    apiRequest<UnitMember>(`/api/v1/units/${encodeURIComponent(unitId)}/members`, { method: "POST", body: JSON.stringify(input) }),
  removeMember: (unitId: string, userId: string) =>
    apiRequest<null>(`/api/v1/units/${encodeURIComponent(unitId)}/members/${encodeURIComponent(userId)}`, { method: "DELETE" }),
  suggestedRecipients: (unitId: string) =>
    apiRequest<UnitMember[]>(`/api/v1/units/${encodeURIComponent(unitId)}/suggested-recipients`),
};
