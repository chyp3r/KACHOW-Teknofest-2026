export interface EvrakFields {
  sayi?: string | null;
  tarih?: string | null;
  konu?: string | null;
  muhatap?: string | null;
  gonderen_kurum?: string | null;
  ilgi?: string[];
  ekler?: string[];
  imza_sahibi?: string | null;
  imza_unvani?: string | null;
  gizlilik_derecesi?: string | null;
  ivedilik?: string | null;
  basvuran_adi?: string | null;
  adres?: string | null;
  iletisim?: string | null;
  entities?: string[];
}

export interface MissingFieldItem {
  key: string;
  label: string;
  severity: string;
  mevzuat: string;
  reason: string;
}

export interface MevzuatReference {
  mevzuat: string;
  aciklama: string;
}

export interface DetectedMarkItem {
  kind: "signature" | "stamp" | "handwriting";
  page: number;
  bbox: [number, number, number, number];
  confidence: number;
}

export interface SignatureAssessment {
  is_signed: boolean;
  has_stamp: boolean;
  marks: DetectedMarkItem[];
}

export interface DocumentMetadata {
  file_name: string;
  storage_path: string;
  upload_time: string;
  document_type: string;
  document_type_label: string;
  compliance_status: string;
  summary: string;
}

export interface DocumentAnalysis extends DocumentMetadata {
  analysis_id?: string;
  extraction: {
    extractor: string;
    page_count: number;
    char_count: number;
    used_ocr: boolean;
    scrubbed_markers?: string[];
  };
  fields: EvrakFields;
  missing_fields: MissingFieldItem[];
  mevzuat_references: MevzuatReference[];
  guardrail: {
    sensitivity_level: SensitivityLevel;
    pii_findings: Array<{
      kind: string;
      preview: string;
    }>;
    requires_human_review: boolean;
    reasons: string[];
  };
  // Optional: the backend always sends it (a Pydantic default_factory), but
  // kept optional here so existing test fixtures that predate this field
  // don't all need updating just to type-check.
  signature?: SignatureAssessment;
  // Absent (undefined) on old cached fixtures; `null` is the backend's own
  // "not yet generated" value (see DocumentAnalysisResponseSchema's own
  // comment) -- on-demand only, never populated by the initial analyze
  // call. Populated in place by POST /documents/{path}/detailed-summary.
  detailed_summary?: string | null;
}

export type ReasoningLevel = "fast" | "balanced" | "deep";

export interface CorrespondenceType {
  value: string;
  label: string;
}

export interface InfoQuestion {
  key: string;
  label: string;
  why?: string;
  example?: string | null;
  required?: boolean;
}

export interface DraftResult {
  draft_id: string;
  draft: string;
  confidence_score: number;
  requires_human_approval: boolean;
  attempts: number;
  verification: Record<string, unknown>;
  judge: Record<string, unknown>;
  missing_information: InfoQuestion[];
  destination: string;
  justification: string;
}

export interface DraftRequest {
  storage_path: string;
  classification: {
    document_type: string;
    document_type_label: string;
    summary: string;
    fields: EvrakFields;
    missing_fields: MissingFieldItem[];
    mevzuat_references: MevzuatReference[];
  };
  instructions: string;
  correspondence_type: string | null;
  reasoning_level: ReasoningLevel;
}

// Knowledge graph -- see backend/app/domains/documents/knowledge_graph.py.
// One flat shape per node/edge kind rather than a discriminated union,
// mirroring the backend's own GraphNode/GraphEdge dataclasses. v2 added
// Entity/Konu node types (entity_kind/surface_forms only meaningful on
// "entity" nodes) and the generic `attributes` payload the node inspector
// reads (currently populated on "document" nodes only -- madde/kanun/entity
// already have everything they need in the typed fields above it).
export interface GraphNode {
  id: string;
  node_type: "document" | "madde" | "kanun" | "entity" | "konu";
  label: string;
  storage_path: string | null;
  file_name: string | null;
  document_type_label: string | null;
  compliance_status: string | null;
  has_analysis: boolean | null;
  kanun: string | null;
  madde: string | null;
  field_labels: string[];
  document_count: number | null;
  entity_kind: "kurum" | "kisi" | "diger" | null;
  surface_forms: string[];
  attributes: Record<string, string | number | boolean | null>;
}

export interface GraphEdge {
  source: string;
  target: string;
  edge_type: "ihlal" | "atif" | "muhatap" | "gonderen" | "bahseder" | "konu";
  source_kind: "rule" | "llm";
  field_key: string | null;
  field_label: string | null;
  severity: string | null;
  reason: string | null;
  aciklama: string | null;
  raw: string | null;
}

export interface TopBreachedMadde {
  madde_id: string;
  kanun: string;
  madde: string;
  field_labels: string[];
  document_count: number;
}

export interface GraphInsights {
  document_count: number;
  madde_count: number;
  kanun_count: number;
  entity_count: number;
  konu_count: number;
  rule_edge_count: number;
  llm_edge_count: number;
  unresolved_reference_count: number;
  top_breached_madde: TopBreachedMadde | null;
}

export interface KnowledgeGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  insights: GraphInsights;
}

// GET /documents/graph's own envelope -- the corpus view adds pagination-ish
// metadata the single-document neighbourhood (KnowledgeGraph alone) has no use for.
export interface CorpusGraph extends KnowledgeGraph {
  truncated: boolean;
  total_document_count: number;
  hidden_document_count: number;
}
import type { SensitivityLevel } from "./security";
