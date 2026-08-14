import { AlertCircle, CheckCircle2, Route, XCircle } from "lucide-react";

// The shape of a completed turn's `details.draft`/`details.routing`, as
// assembled by backend app.ai.workflows.planning_graph._compile_final_output.
// Loosely typed on purpose -- `details` travels the wire as
// Record<string, unknown> (see ChatMessage.details) and this is the one
// place that reaches into it, so a shape drift fails soft (a field just
// doesn't render) rather than throwing.
// One row of app.ai.verification.confidence_rules.AppliedRule -- the
// deterministic rule table's own breakdown of confidence_score, so "why is
// this score 62?" has a satisfying answer instead of a bare number.
interface AppliedRule {
  rule_id: string;
  label: string;
  occurrences: number;
  penalty_applied: number;
  forces_approval: boolean;
}

interface DraftDetails {
  draft?: string;
  status?: string;
  combined_score?: number;
  requires_human_approval?: boolean;
  evaluation_notes?: string;
  rejection_reason?: string;
  changelog?: { summary?: string };
  applied_rules?: AppliedRule[];
}

interface RoutingDetails {
  routed_unit?: string;
}

// The score/approval/routing/rejection facts that used to be concatenated
// onto the chat reply as free text (see backend ChatService._select_reply)
// now live here instead, read straight off the message's structured
// `details` rather than baked into a string.
export function DraftMetaStrip({ details }: { details?: Record<string, unknown> }) {
  const draft = details?.draft as DraftDetails | undefined;
  const routing = details?.routing as RoutingDetails | undefined;
  if (!draft?.draft) return null;

  const hasScore = typeof draft.combined_score === "number";
  const routedUnit = routing?.routed_unit;
  const isRejected = draft.status === "REJECTED";
  const isReviseExhausted = draft.status === "REVISE_REQUESTED";
  const changelogSummary = draft.changelog?.summary;
  // Every row here already fired at least once (see confidence_rules.
  // score_findings) -- no further filtering needed.
  const appliedRules = draft.applied_rules ?? [];

  if (
    !hasScore &&
    !routedUnit &&
    !draft.requires_human_approval &&
    !isRejected &&
    !isReviseExhausted &&
    !changelogSummary
  ) {
    return null;
  }

  return (
    <div className="draft-meta-strip">
      {hasScore && (
        <span className="draft-meta-chip">
          Güven skoru: {draft.combined_score}/100
        </span>
      )}
      {appliedRules.length > 0 && (
        <details className="message-logs draft-meta-rules">
          <summary>Skor dökümü ({appliedRules.length})</summary>
          {appliedRules.map((rule) => (
            <p key={rule.rule_id}>
              {rule.label}
              {rule.occurrences > 1 ? ` (×${rule.occurrences})` : ""}
              {rule.penalty_applied > 0 ? ` — -${rule.penalty_applied} puan` : ""}
              {rule.forces_approval ? " · insan onayı gerektirir" : ""}
            </p>
          ))}
        </details>
      )}
      {routedUnit && (
        <span className="draft-meta-chip">
          <Route size={13} />
          Önerilen birim: {routedUnit}
        </span>
      )}
      {draft.requires_human_approval && !isRejected && (
        <span className="draft-meta-chip draft-meta-warning">
          <AlertCircle size={13} />
          İnsan onayı gerekiyor
          {draft.evaluation_notes ? `: ${draft.evaluation_notes}` : ""}
        </span>
      )}
      {isRejected && (
        <span className="draft-meta-chip draft-meta-danger">
          <XCircle size={13} />
          Reddedildi
          {draft.rejection_reason ? ` (gerekçe: ${draft.rejection_reason})` : ""}
        </span>
      )}
      {isReviseExhausted && (
        <span className="draft-meta-chip draft-meta-warning">
          <AlertCircle size={13} />
          Revizyon turu sınırına ulaşıldı; bu son sürüm korundu.
        </span>
      )}
      {hasScore && !draft.requires_human_approval && !isRejected && !isReviseExhausted && (
        <span className="draft-meta-chip draft-meta-success">
          <CheckCircle2 size={13} />
          Hazır
        </span>
      )}
      {changelogSummary && (
        <span className="draft-meta-chip">Değişiklik özeti: {changelogSummary}</span>
      )}
    </div>
  );
}
