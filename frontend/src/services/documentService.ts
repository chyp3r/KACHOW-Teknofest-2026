import { apiRequest } from "./apiClient";
import type { PaginatedResponse } from "../types/api";
import type {
  CorrespondenceType,
  DocumentAnalysis,
  DocumentMetadata,
  DocumentText,
  DraftRequest,
  DraftResult,
  EvrakFields,
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
  updateFields(storagePath: string, fields: EvrakFields): Promise<DocumentAnalysis> {
    const safePath = storagePath.split("/").map(encodeURIComponent).join("/");
    return apiRequest(`/api/v1/documents/${safePath}/fields`, {
      method: "PATCH",
      body: JSON.stringify({ fields }),
    });
  },
  // Slow on purpose: builds it on-demand rather than eagerly on every
  // upload (measured 184-288s server-side on real documents -- see
  // backend/app/ai/summarization.py's own module docstring). apiClient sets
  // no request timeout, so this plain POST survives the wait unmodified.
  generateDetailedSummary(storagePath: string): Promise<DocumentAnalysis> {
    const safePath = storagePath.split("/").map(encodeURIComponent).join("/");
    return apiRequest(`/api/v1/documents/${safePath}/detailed-summary`, {
      method: "POST",
    });
  },
  getText(storagePath: string): Promise<DocumentText> {
    const safePath = storagePath.split("/").map(encodeURIComponent).join("/");
    return apiRequest(`/api/v1/documents/${safePath}/text`);
  },
  // The client edits `pages`, never a joined `extracted_text` -- the server
  // always re-derives the join itself (see backend's own reasoning: there
  // is no lossless inverse of `"\n\n".join(pages)`).
  updateText(storagePath: string, pages: string[]): Promise<DocumentAnalysis> {
    const safePath = storagePath.split("/").map(encodeURIComponent).join("/");
    return apiRequest(`/api/v1/documents/${safePath}/text`, {
      method: "PUT",
      body: JSON.stringify({ pages }),
    });
  },
  // Slow on purpose, same reasoning as generateDetailedSummary above: a
  // full glm-ocr pass, no request timeout to fight client-side.
  reextractText(storagePath: string): Promise<DocumentAnalysis> {
    const safePath = storagePath.split("/").map(encodeURIComponent).join("/");
    return apiRequest(`/api/v1/documents/${safePath}/re-extract`, {
      method: "POST",
    });
  },
  remove(storagePath: string): Promise<{ deleted: boolean }> {
    const safePath = storagePath.split("/").map(encodeURIComponent).join("/");
    return apiRequest(`/api/v1/documents/${safePath}`, { method: "DELETE" });
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
