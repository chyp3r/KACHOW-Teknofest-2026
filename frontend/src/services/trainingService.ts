import { apiFetch, apiRequest, apiErrorFromResponse } from "./apiClient";
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
  async exportSamples(companyId: string): Promise<void> {
    const response = await apiFetch(
      `/api/v1/companies/${encodeURIComponent(companyId)}/training-samples/export`,
    );
    if (!response.ok) throw await apiErrorFromResponse(response);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${companyId}-training-samples.jsonl`;
    link.click();
    URL.revokeObjectURL(url);
  },
};
