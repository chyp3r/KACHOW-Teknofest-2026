import { apiRequest } from "./apiClient";
import type {
  RootCompanyStats,
  RootHealth,
  RootOverview,
  RootUserInsights,
  RootUserStats,
} from "../types/management";

export const rootService = {
  overview: () => apiRequest<RootOverview>("/api/v1/root/overview"),
  companies: () => apiRequest<RootCompanyStats[]>("/api/v1/root/companies/stats"),
  users: () => apiRequest<RootUserStats>("/api/v1/root/users/stats"),
  userInsights: () => apiRequest<RootUserInsights>("/api/v1/root/users/insights"),
  health: () => apiRequest<RootHealth>("/api/v1/root/health"),
};
