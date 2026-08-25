import type { User, UserRole } from "./users";

export interface UsageSummary {
  period: string;
  used: number;
  limit: number | null;
}

export interface AnalyticsSummary {
  company_id: string;
  document_count: number;
  draft_stats: {
    total: number;
    avg_confidence_score: number | null;
    requires_human_approval: number;
  };
  run_status: Record<string, number>;
  active_users_7d: number;
  guardrail_blocked_total: number;
  usage: Record<string, UsageSummary>;
}

export interface TimeseriesPoint {
  bucket: string;
  count: number;
}

export interface UnitVolume {
  destination: string | null;
  unit_id: string | null;
  count: number;
}

export interface GuardrailBreakdown {
  stage: string;
  kind: string;
  decision: string;
  count: number;
}

export interface AnalyticsLinks {
  grafana_url: string;
  langfuse_url: string;
}

export interface PermissionGrant {
  id: string;
  company_id: string;
  subject_type: string;
  subject_id: string;
  action: string;
  resource_type: string;
  resource_selector: Record<string, unknown>;
  effect: "permit" | "deny";
  priority: number;
  valid_from: string | null;
  valid_until: string | null;
  granted_by: string;
  revoked_at: string | null;
  reason: string | null;
  created_at: string;
}

export interface PermissionGrantInput {
  action: string;
  resource_type: string;
  resource_selector: Record<string, unknown>;
  effect: "permit" | "deny";
  priority?: number;
  valid_until?: string | null;
  reason?: string | null;
}

export interface UnitMember {
  user_id: string;
  username: string;
  email: string;
  is_primary: boolean;
  role_in_unit: string | null;
}

export interface Company {
  id: string;
  name: string;
  slug: string;
  tax_number: string | null;
  is_active: boolean;
  settings: Record<string, unknown>;
}

export interface CompanyProfile {
  company_id: string;
  version: number;
  display_name: string;
  short_name: string;
  agent_name: string;
  letterhead: string;
  default_signer_title: string;
  updated_at: string | null;
}

export interface CompanyRule {
  id?: string | null;
  text: string;
  severity: "zorunlu" | "onerilen";
  enabled: boolean;
}

export interface CompanyRules {
  company_id: string;
  version: number;
  rules: CompanyRule[];
  updated_at: string | null;
}

export interface CompanyAdapter {
  company_id: string;
  version: number;
  style_rules: string[];
  preferred_examples: string[];
  avoided_patterns: string[];
  trained_at: string | null;
  sample_count: number;
}

export interface AuditEntry {
  id: string;
  company_id: string | null;
  seq: number;
  actor_user_id: string | null;
  actor_role: UserRole | null;
  acting_as_company_id: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  decision: string;
  reason: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  correlation_id: string | null;
  created_at: string;
}

export interface ChainVerification {
  valid: boolean;
  rows_checked: number;
  broken_at_seq: number | null;
  reason: string | null;
}

export interface DocumentPool {
  id: string;
  owner_type: string;
  owner_id: string;
  name: string;
  is_default: boolean;
}

export interface DocumentPoolItem {
  id: string;
  pool_id: string;
  document_id: string;
  file_name: string | null;
  added_by: string;
  source: string;
  note: string | null;
  acknowledged_at: string | null;
  created_at: string;
}

export interface PoolPushResult {
  user_id: string;
  status: "pushed" | "denied_clearance" | "not_found" | string;
  reason: string | null;
}

export interface RootOverview {
  total_companies: number;
  total_users: number;
  total_documents: number;
  total_drafts: number;
  run_status: Record<string, number>;
  total_runs: number;
  error_rate: number;
}

export interface RootCompanyStats {
  company_id: string;
  name: string;
  slug?: string;
  user_count: number;
  document_count: number;
  draft_count: number;
}

export interface RootUserStats {
  by_role: Record<string, number>;
  active_7d: number;
  active_30d: number;
  seats_by_company: Array<{ company_id: string; name: string; user_count: number }>;
}

export interface RootHealth {
  status: string;
  project?: string;
  environment?: string;
  dependencies?: Record<"postgres" | "redis" | "qdrant" | "ollama", import("./health").DependencyHealth>;
  checkpointer?: import("./health").DependencyHealth;
  router_semantic?: import("./health").DependencyHealth;
  companies_last_activity: Record<string, string | null>;
  [key: string]: unknown;
}

export type CompanyAdmin = User;
