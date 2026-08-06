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
import type { SensitivityLevel } from "./security";
