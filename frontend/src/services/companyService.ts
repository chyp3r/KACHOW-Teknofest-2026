import { apiRequest } from "./apiClient";
import type { PaginatedResponse } from "../types/api";
import type {
  Company,
  CompanyAdapter,
  CompanyProfile,
  CompanyRule,
  CompanyRules,
} from "../types/management";
import type { User } from "../types/users";

const path = (companyId: string) => `/api/v1/companies/${encodeURIComponent(companyId)}`;

export const companyService = {
  list: (page = 1, size = 100) =>
    apiRequest<PaginatedResponse<Company>>(`/api/v1/companies?page=${page}&size=${size}`),
  get: (companyId: string) => apiRequest<Company>(path(companyId)),
  create: (input: { name: string; slug: string; tax_number?: string | null }) =>
    apiRequest<Company>("/api/v1/companies", { method: "POST", body: JSON.stringify(input) }),
  update: (companyId: string, input: Partial<Pick<Company, "name" | "tax_number" | "is_active" | "settings">>) =>
    apiRequest<Company>(path(companyId), { method: "PATCH", body: JSON.stringify(input) }),
  remove: (companyId: string) => apiRequest<null>(path(companyId), { method: "DELETE" }),
  assignAdmin: (companyId: string, userId: string) =>
    apiRequest<User>(`${path(companyId)}/admins`, { method: "POST", body: JSON.stringify({ user_id: userId }) }),
  profile: (companyId: string) => apiRequest<CompanyProfile>(`${path(companyId)}/profile`),
  updateProfile: (companyId: string, profile: Omit<CompanyProfile, "company_id" | "version" | "updated_at">) =>
    apiRequest<CompanyProfile>(`${path(companyId)}/profile`, { method: "PUT", body: JSON.stringify(profile) }),
  rules: (companyId: string) => apiRequest<CompanyRules>(`${path(companyId)}/rules`),
  updateRules: (companyId: string, rules: CompanyRule[]) =>
    apiRequest<CompanyRules>(`${path(companyId)}/rules`, { method: "PUT", body: JSON.stringify({ rules }) }),
  adapter: (companyId: string) => apiRequest<CompanyAdapter>(`${path(companyId)}/adapter`),
  updateAdapter: (companyId: string, input: Pick<CompanyAdapter, "style_rules" | "preferred_examples" | "avoided_patterns">) =>
    apiRequest<CompanyAdapter>(`${path(companyId)}/adapter`, { method: "PUT", body: JSON.stringify(input) }),
};
