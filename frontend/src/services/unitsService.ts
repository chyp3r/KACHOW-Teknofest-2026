import { apiRequest } from "./apiClient";
import type { Unit } from "../types/units";

export const unitsService = {
  list: () => apiRequest<Unit[]>("/api/v1/units"),
};
