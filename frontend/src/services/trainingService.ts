import { apiRequest } from "./apiClient";
import type { PaginatedResponse } from "../types/api";
import type { TrainingRun, TrainingSample, TrainingSampleStats } from "../types/training";

export const trainingService = {
  compileSamples: (companyId: string) =>
    apiRequest<PaginatedResponse<TrainingSample>>(
      `/api/v1/companies/${encodeURIComponent(companyId)}/training-samples/compile`,
      { method: "POST" },
    ),
  listSamples: (companyId: string, page = 1, size = 20) =>
    apiRequest<PaginatedResponse<TrainingSample>>(
      `/api/v1/companies/${encodeURIComponent(companyId)}/training-samples?page=${page}&size=${size}`,
    ),
  stats: (companyId: string) =>
    apiRequest<TrainingSampleStats>(
      `/api/v1/companies/${encodeURIComponent(companyId)}/training-samples/stats`,
    ),
  deleteSample: (sampleId: string) =>
    apiRequest<{ deleted: boolean }>(`/api/v1/training-samples/${encodeURIComponent(sampleId)}`, {
      method: "DELETE",
    }),
  triggerRun: (companyId: string) =>
    apiRequest<TrainingRun>(`/api/v1/companies/${encodeURIComponent(companyId)}/training-runs`, {
      method: "POST",
    }),
  listRuns: (companyId: string, page = 1, size = 20) =>
    apiRequest<PaginatedResponse<TrainingRun>>(
      `/api/v1/companies/${encodeURIComponent(companyId)}/training-runs?page=${page}&size=${size}`,
    ),
};
