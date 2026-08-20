import { apiRequest } from "./apiClient";
import type { PaginatedResponse } from "../types/api";
import type { DraftShare, PersistedDraft } from "../types/drafts";
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
  inbox: () =>
    collectPages((page) =>
      apiRequest<PaginatedResponse<DraftShare>>(`/api/v1/drafts/inbox?page=${page}&size=100`),
    ),
  outbox: () =>
    collectPages((page) =>
      apiRequest<PaginatedResponse<DraftShare>>(`/api/v1/drafts/outbox?page=${page}&size=100`),
    ),
  send: (draftId: string, recipientIds: string[], message?: string) =>
    apiRequest<DraftShare[]>(`/api/v1/drafts/${encodeURIComponent(draftId)}/send`, {
      method: "POST",
      body: JSON.stringify({ recipient_ids: recipientIds, message: message || null }),
    }),
  respond: (shareId: string, action: "accept" | "reject", responseNote?: string) =>
    apiRequest<DraftShare>(`/api/v1/drafts/shares/${encodeURIComponent(shareId)}/${action}`, {
      method: "POST",
      body: JSON.stringify({ response_note: responseNote || null }),
    }),
  markShareRead: (shareId: string) =>
    apiRequest<DraftShare>(`/api/v1/drafts/shares/${encodeURIComponent(shareId)}/read`, {
      method: "POST",
    }),
  revokeShare: (shareId: string) =>
    apiRequest<DraftShare>(`/api/v1/drafts/shares/${encodeURIComponent(shareId)}`, {
      method: "DELETE",
    }),
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
