import { apiRequest } from "./apiClient";
import type { PaginatedResponse } from "../types/api";
import type { DocumentPool, DocumentPoolItem, PoolPushResult } from "../types/pools";

export const poolService = {
  mine: () => apiRequest<DocumentPool>("/api/v1/pools/me"),
  items: (poolId: string, page = 1, size = 100) =>
    apiRequest<PaginatedResponse<DocumentPoolItem>>(`/api/v1/pools/${encodeURIComponent(poolId)}/items?page=${page}&size=${size}`),
  add: (poolId: string, documentId: string, note?: string) =>
    apiRequest<DocumentPoolItem>(`/api/v1/pools/${encodeURIComponent(poolId)}/items`, {
      method: "POST", body: JSON.stringify({ document_id: documentId, note: note ?? null }),
    }),
  push: (input: { document_id: string; recipient_ids?: string[]; unit_id?: string; note?: string }) =>
    apiRequest<PoolPushResult[]>("/api/v1/pools/push", { method: "POST", body: JSON.stringify(input) }),
  remove: (poolId: string, itemId: string) =>
    apiRequest<null>(`/api/v1/pools/${encodeURIComponent(poolId)}/items/${encodeURIComponent(itemId)}`, { method: "DELETE" }),
  acknowledge: (itemId: string) =>
    apiRequest<DocumentPoolItem>(`/api/v1/pools/items/${encodeURIComponent(itemId)}/acknowledge`, { method: "POST" }),
  adopt: (itemId: string) =>
    apiRequest<DocumentPoolItem>(`/api/v1/pools/items/${encodeURIComponent(itemId)}/adopt`, { method: "POST" }),
};
