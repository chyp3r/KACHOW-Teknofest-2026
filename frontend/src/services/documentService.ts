import { apiRequest } from "./apiClient";
import type { PaginatedResponse } from "../types/api";
import type {
  CorrespondenceType,
  DocumentAnalysis,
  DocumentMetadata,
  DraftRequest,
  DraftResult,
} from "../types/documents";
import { collectPages } from "./pagination";

export const documentService = {
  async list(): Promise<DocumentMetadata[]> {
    const result = await collectPages((page) =>
      apiRequest<PaginatedResponse<DocumentMetadata>>(
        `/api/v1/documents?page=${page}&size=100`,
      ),
    );
    return result.items;
  },
  analyze(file: File): Promise<DocumentAnalysis> {
    const body = new FormData();
    body.append("file", file);
    return apiRequest("/api/v1/documents/analyze", { method: "POST", body });
  },
  getAnalysis(storagePath: string): Promise<DocumentAnalysis> {
    const safePath = storagePath.split("/").map(encodeURIComponent).join("/");
    return apiRequest(`/api/v1/documents/${safePath}`);
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
