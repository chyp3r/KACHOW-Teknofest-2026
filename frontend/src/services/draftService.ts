import { apiFetch, apiRequest } from "./apiClient";
import type { PaginatedResponse } from "../types/api";
import type { DraftShare, PersistedDraft } from "../types/drafts";
import { collectPages } from "./pagination";

export type DraftExportFormat = "docx" | "pdf";

function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const utf8 = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1]);
    } catch {
      /* aşağıdaki düz filename'e düş */
    }
  }
  const plain = header.match(/filename="?([^";]+)"?/i);
  return plain?.[1] ?? fallback;
}

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
  approveReview: (draftId: string) =>
    apiRequest<PersistedDraft>(`/api/v1/drafts/${encodeURIComponent(draftId)}/review/approve`, {
      method: "POST",
    }),
  remove: (draftId: string) =>
    apiRequest<{ deleted: boolean }>(`/api/v1/drafts/${encodeURIComponent(draftId)}`, {
      method: "DELETE",
    }),

  /** Taslağı docx/pdf olarak indirir: binary yanıtı bir blob'a çevirip
   * tarayıcıda bir "kaydet" tetikler. Zarf tabanlı `apiRequest` JSON
   * beklediği için ham `apiFetch` (auth + refresh davranışı korunur). */
  export: async (
    draftId: string,
    fmt: DraftExportFormat,
    version?: number,
  ): Promise<void> => {
    const response = await apiFetch(
      `/api/v1/drafts/${encodeURIComponent(draftId)}/export?fmt=${fmt}`,
    );
    if (!response.ok) {
      throw new Error("Taslak indirilemedi.");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filenameFromDisposition(
      response.headers.get("Content-Disposition"),
      `taslak-v${version ?? 1}.${fmt}`,
    );
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  },
};
