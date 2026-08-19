export type ArtifactKind = "draft" | "document";
export type TransferChannel = "chat" | "ai" | "rest";
export type TransferStatus = "executed" | "failed" | "withdrawn";

export interface ArtifactTransfer {
  id: string;
  artifact_kind: ArtifactKind;
  source_artifact_id: string;
  source_version: number | null;
  snapshot_ref: string | null;
  sender_id: string;
  recipient_id: string;
  conversation_id: string | null;
  message_id: string | null;
  channel: TransferChannel;
  ai_suggested: boolean;
  cross_unit: boolean;
  policy_decision: string;
  policy_reason: string | null;
  status: TransferStatus;
  created_at: string;
}

export interface RecipientRecommendation {
  user_id: string;
  username: string;
  source: "favorite_in_unit" | "unit_member";
  unit_id: string;
  unit_name: string;
}

export interface GroupTransferResult {
  recipient_id: string;
  status: string;
  transfer_id: string | null;
  reason: string | null;
}
