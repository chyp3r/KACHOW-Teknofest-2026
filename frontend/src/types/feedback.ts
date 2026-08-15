// Mirrors backend app.domains.feedback.schema.feedback_schema -- the
// RLHF-style data-collection layer's request/response shapes (Faz C1).

export type FeedbackTargetKind = "draft" | "revision" | "assist_reply" | "routing";
export type FeedbackSignal = "like" | "dislike";

export interface FeedbackVoteRequest {
  target_kind: FeedbackTargetKind;
  signal: FeedbackSignal;
  // The exact rated text -- hashed server-side, never itself persisted
  // (see backend FeedbackModel's docstring). This is what makes voting
  // again on the same text update the existing vote instead of duplicating
  // it, even before the message has a durable id.
  content: string;
  comment?: string;
  dimensions?: Record<string, boolean>;
  session_id?: string;
  message_id?: string;
  draft_id?: string;
  context?: Record<string, unknown>;
}

export interface FeedbackEntry {
  id: string;
  target_kind: FeedbackTargetKind;
  signal: FeedbackSignal;
  comment?: string | null;
  dimensions?: Record<string, boolean> | null;
  content_hash: string;
  context?: Record<string, unknown> | null;
  session_id?: string | null;
  message_id?: string | null;
  draft_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface FeedbackStats {
  total: number;
  likes: number;
  dislikes: number;
  by_target_kind: Record<string, number>;
}
