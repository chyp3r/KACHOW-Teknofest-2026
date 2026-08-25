import type { PersistedDraft } from "../../types/drafts";

export type DraftStateCategory = "ready" | "review" | "pending";

export function draftState(draft: PersistedDraft) {
  const issues = (draft.missing_information?.length ?? 0) + (draft.requires_human_approval ? 1 : 0);
  const status = draft.status?.toLocaleLowerCase("tr-TR");

  if (status === "sent") return { label: "Gönderildi", tone: "info" as const, issues: 0, category: "ready" as const };
  if (issues > 0) return { label: "İnceleme gerekli", tone: "warning" as const, issues, category: "review" as const };
  if ((draft.confidence_score ?? 0) >= 80 || status === "ready" || status === "approved") {
    return { label: "Hazır", tone: "success" as const, issues: 0, category: "ready" as const };
  }
  return { label: "Taslak", tone: "pending" as const, issues: 0, category: "pending" as const };
}
