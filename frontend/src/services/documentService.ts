import { apiRequest } from "./apiClient";
import type { PaginatedResponse } from "../types/api";
import type {
  CorrespondenceType,
  DocumentAnalysis,
  DocumentMetadata,
  DraftRequest,
  DraftResult,
} from "../types/documents";

export const documentService = {
  async list(): Promise<DocumentMetadata[]> {
    const result = await apiRequest<
      PaginatedResponse<DocumentMetadata> | DocumentMetadata[]
    >("/api/v1/documents");
    return Array.isArray(result) ? result : result.items;
  },
  analyze(file: File): Promise<DocumentAnalysis> {
    const body = new FormData();
    body.append("file", file);
    return apiRequest("/api/v1/documents/analyze", { method: "POST", body });
  },
  getAnalysis(storagePath: string): Promise<DocumentAnalysis> {
    return apiRequest(`/api/v1/documents/${encodeURIComponent(storagePath)}`);
  },
  correspondenceTypes(): Promise<CorrespondenceType[]> {
    return apiRequest("/api/v1/documents/correspondence-types");
  },
  createDraft(request: DraftRequest): Promise<DraftResult> {
    return apiRequest("/api/v1/documents/draft", {
      method: "POST",
      body: JSON.stringify(request),
    });
  },
};
