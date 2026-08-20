import { apiRequest } from "./apiClient";
import type { CorpusGraph, KnowledgeGraph } from "../types/documents";

export const graphService = {
  corpusGraph(): Promise<CorpusGraph> {
    return apiRequest("/api/v1/documents/graph");
  },
  documentGraph(storagePath: string): Promise<KnowledgeGraph> {
    const safePath = storagePath.split("/").map(encodeURIComponent).join("/");
    return apiRequest(`/api/v1/documents/${safePath}/graph`);
  },
};
