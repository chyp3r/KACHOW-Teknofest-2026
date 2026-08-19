import { apiRequest } from "./apiClient";
import type { PaginatedResponse } from "../types/api";
import type { PersistedDraft } from "../types/drafts";
import { collectPages } from "./pagination";

export const draftService = {
  list: () =>
    collectPages((page) =>
      apiRequest<PaginatedResponse<PersistedDraft>>(`/api/v1/drafts?page=${page}&size=100`),
    ),
  get: (draftId: string) =>
    apiRequest<PersistedDraft>(`/api/v1/drafts/${encodeURIComponent(draftId)}`),
  versions: (draftId: string) =>
    apiRequest<PersistedDraft[]>(`/api/v1/drafts/${encodeURIComponent(draftId)}/versions`),
  updateDestination: (draftId: string, destination: string) =>
    apiRequest<PersistedDraft>(`/api/v1/drafts/${encodeURIComponent(draftId)}/destination`, {
      method: "PATCH",
      body: JSON.stringify({ destination }),
    }),
  remove: (draftId: string) =>
    apiRequest<{ deleted: boolean }>(`/api/v1/drafts/${encodeURIComponent(draftId)}`, {
      method: "DELETE",
    }),
};
