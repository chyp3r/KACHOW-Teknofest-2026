import { apiRequest } from "./apiClient";
import type { HealthStatus } from "../types/health";

export const healthService = {
  get: (deep = false) => apiRequest<HealthStatus>(`/api/v1/health${deep ? "?deep=true" : ""}`),
};
