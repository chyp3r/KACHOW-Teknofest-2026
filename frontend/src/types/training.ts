// Mirrors backend app.domains.training.schema.training_schema -- the
// automated style-adapter training pipeline (Faz C3, #187).

export interface TrainingSample {
  id: string;
  training_run_id?: string | null;
  source: string;
  source_feedback_id?: string | null;
  source_draft_id?: string | null;
  prompt_context?: string | null;
  chosen?: string | null;
  rejected?: string | null;
  weight: number;
  created_at: string;
  updated_at: string;
}

export interface TrainingSampleStats {
  total: number;
  by_source: Record<string, number>;
  min_samples_required: number;
  samples_remaining_to_threshold: number;
}

export interface TrainingRun {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | "skipped";
  trigger: string;
  sample_count?: number | null;
  metrics?: Record<string, unknown> | null;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
}
