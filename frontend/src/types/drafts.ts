import type { InfoQuestion } from "./documents";

export interface PersistedDraft {
  id: string;
  user_id: string | null;
  session_id: string | null;
  document_id: string | null;
  version: number;
  parent_draft_id: string | null;
  content: string;
  correspondence_type: string | null;
  destination: string | null;
  status: string | null;
  confidence_score: number | null;
  requires_human_approval: boolean | null;
  attempts: number | null;
  verification: Record<string, unknown> | null;
  judge: Record<string, unknown> | null;
  missing_information: InfoQuestion[] | null;
  instructions: string | null;
  created_at: string;
  updated_at: string;
}
