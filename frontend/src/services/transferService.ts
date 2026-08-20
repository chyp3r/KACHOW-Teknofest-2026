import { apiRequest } from "./apiClient";
import type { ArtifactKind, ArtifactTransfer, GroupTransferResult, RecipientRecommendation } from "../types/transfers";

export const transferService = {
  send: (params: {
    recipientId: string;
    artifactKind: ArtifactKind;
    sourceArtifactId: string;
    sourceVersion?: number;
    idempotencyKey?: string;
  }) =>
    apiRequest<ArtifactTransfer>("/api/v1/transfers/send", {
      method: "POST",
      body: JSON.stringify({
        recipient_id: params.recipientId,
        artifact_kind: params.artifactKind,
        source_artifact_id: params.sourceArtifactId,
        source_version: params.sourceVersion ?? null,
        idempotency_key: params.idempotencyKey ?? null,
      }),
    }),
  sendGroup: (params: {
    recipientIds: string[];
    artifactKind: ArtifactKind;
    sourceArtifactId: string;
    sourceVersion?: number;
  }) =>
    apiRequest<GroupTransferResult[]>("/api/v1/transfers/send-group", {
      method: "POST",
      body: JSON.stringify({
        recipient_ids: params.recipientIds,
        artifact_kind: params.artifactKind,
        source_artifact_id: params.sourceArtifactId,
        source_version: params.sourceVersion ?? null,
      }),
    }),
  get: (transferId: string) =>
    apiRequest<ArtifactTransfer>(`/api/v1/transfers/${encodeURIComponent(transferId)}`),
  recommendations: (draftId: string, limit = 5) =>
    apiRequest<RecipientRecommendation[]>(
      `/api/v1/transfers/recommendations?draft_id=${encodeURIComponent(draftId)}&limit=${limit}`,
    ),
};
