import { capitalizeFirst } from "../../utils/text";

/** Backend emits English decision codes; the UI shows Turkish. */
const DECISION_LABELS: Record<string, string> = {
  flagged: "İşaretlendi",
  blocked: "Engellendi",
  redacted: "Maskelendi",
  needs_review: "İnceleme gerekli",
  passed: "Sorun bulunmadı",
};

export function guardrailDecisionLabel(decision: string): string {
  return DECISION_LABELS[decision] ?? decision.replace(/_/g, " ");
}

/**
 * Reason strings come from the backend output gate as lowercase "kinds"
 * (e.g. "1 doğrulanamayan ifade kaldırıldı"). Present them as sentences and
 * keep the PII acronym uppercased.
 */
export function formatGuardrailReason(reason: string): string {
  return capitalizeFirst(reason.replace(/\bpii\b/gi, "PII"));
}
