import { apiRequest } from "./apiClient";
import type { PaginatedResponse } from "../types/api";
import type { AuditEntry, ChainVerification } from "../types/management";

export interface AuditFilters {
  companyId?: string;
  actorUserId?: string;
  action?: string;
  resourceType?: string;
}

function params(filters: AuditFilters, page: number, size: number) {
  const query = new URLSearchParams({ page: String(page), size: String(size) });
  if (filters.companyId) query.set("company_id", filters.companyId);
  if (filters.actorUserId) query.set("actor_user_id", filters.actorUserId);
  if (filters.action) query.set("action", filters.action);
  if (filters.resourceType) query.set("resource_type", filters.resourceType);
  return query;
}

export const auditService = {
  list: (filters: AuditFilters = {}, page = 1, size = 50) =>
    apiRequest<PaginatedResponse<AuditEntry>>(`/api/v1/audit?${params(filters, page, size)}`),
  verify: (companyId?: string) =>
    apiRequest<ChainVerification>(`/api/v1/audit/verify${companyId ? `?company_id=${encodeURIComponent(companyId)}` : ""}`),
};
