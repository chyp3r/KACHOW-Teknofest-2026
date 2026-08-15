import { apiRequest } from "./apiClient";
import type { PaginatedResponse } from "../types/api";
import type { FeedbackEntry, FeedbackStats, FeedbackVoteRequest } from "../types/feedback";

export const feedbackService = {
  submit: (request: FeedbackVoteRequest) =>
    apiRequest<FeedbackEntry>("/api/v1/feedback", {
      method: "POST",
      body: JSON.stringify(request),
    }),
  remove: (feedbackId: string) =>
    apiRequest<{ deleted: boolean }>(`/api/v1/feedback/${encodeURIComponent(feedbackId)}`, {
      method: "DELETE",
    }),
  list: (page = 1, size = 100) =>
    apiRequest<PaginatedResponse<FeedbackEntry>>(`/api/v1/feedback?page=${page}&size=${size}`),
  stats: (companyId: string) =>
    apiRequest<FeedbackStats>(`/api/v1/companies/${encodeURIComponent(companyId)}/feedback/stats`),
};
