import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { AlertCircle, CheckCircle2, ChevronDown, FileDown, FileText, Route, XCircle } from "lucide-react";
import { ApiErrorNotice } from "../../components/ApiErrorNotice";
import { UnitPicker } from "../drafts/UnitPicker";
import { draftService } from "../../services/draftService";
import { queryKeys } from "../../query/queryKeys";

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
  // Injected by the backend (see ChatService._maybe_record_draft) once the
  // turn's draft is persisted -- absent only when draft-history recording
  // itself is disabled or failed, in which case there is nothing to attach
  // a unit picker to and the strip falls back to the plain text chip.
  id?: string;
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
  alternative_units?: string[];
}

// The score/approval/routing/rejection facts that used to be concatenated
// onto the chat reply as free text (see backend ChatService._select_reply)
// now live here instead, read straight off the message's structured
// `details` rather than baked into a string.
export function DraftMetaStrip({ details }: { details?: Record<string, unknown> }) {
  const draft = details?.draft as DraftDetails | undefined;
  const routing = details?.routing as RoutingDetails | undefined;
  const draftId = draft?.id;
  const detailId = useId();
  const [expanded, setExpanded] = useState(false);
  const queryClient = useQueryClient();
  // Chat message details are an immutable snapshot of the turn that created
  // them. The persisted draft is the authoritative source after a human
  // changes its target unit, including after this message remounts on a page
  // reload or history navigation.
  const persistedDraftQuery = useQuery({
    queryKey: queryKeys.draft(draftId ?? ""),
    queryFn: () => draftService.get(draftId!),
    enabled: Boolean(draftId),
    staleTime: 20_000,
  });
  const updateDestinationMutation = useMutation({
    mutationFn: (destination: string) => {
      if (!draftId) throw new Error("Taslak kimliği bulunamadı.");
      return draftService.updateDestination(draftId, destination);
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.draft(updated.id), updated);
      void queryClient.invalidateQueries({ queryKey: ["drafts"] });
    },
  });

  if (!draft?.draft) return null;

  const hasScore = typeof draft.combined_score === "number";
  const persistedDestination = persistedDraftQuery.data?.destination;
  const routedUnit = persistedDestination ?? routing?.routed_unit;
  const destinationOverridden = Boolean(
    persistedDestination
      && routing?.routed_unit
      && persistedDestination !== routing.routed_unit,
  );
  const alternativeUnits = routing?.alternative_units ?? [];
  const isRejected = draft.status === "REJECTED";
  const isReviseExhausted = draft.status === "REVISE_REQUESTED";
  const changelogSummary = draft.changelog?.summary;
  // Every row here already fired at least once (see confidence_rules.
  // score_findings) -- no further filtering needed.
  const appliedRules = draft.applied_rules ?? [];
  const hasControlNotes = Boolean(!isRejected && draft.evaluation_notes);
  const hasExpandedContent = Boolean(
    appliedRules.length > 0 ||
    hasControlNotes ||
    routedUnit ||
    draftId ||
    changelogSummary,
  );

  if (
    !hasScore &&
    !routedUnit &&
    !draftId &&
    !draft.requires_human_approval &&
    !isRejected &&
    !isReviseExhausted &&
    !changelogSummary
  ) {
    return null;
  }

  return (
    <section className="draft-meta-strip" aria-label="Taslak kontrol özeti">
      <header className="draft-meta-header">
        {hasExpandedContent ? (
          <button
            type="button"
            className="draft-meta-toggle"
            aria-expanded={expanded}
            aria-controls={detailId}
            aria-label={expanded ? "Taslak kontrol ayrıntılarını gizle" : "Taslak kontrol ayrıntılarını göster"}
            onClick={() => setExpanded((current) => !current)}
          >
            <span className="draft-score-metric">
              {hasScore ? (
                <>
                  <span>Güven skoru</span>
                  <strong>{draft.combined_score}</strong>
                  <span>/100</span>
                  <span className="sr-only">Güven skoru: {draft.combined_score}/100</span>
                </>
              ) : (
                <strong>Taslak durumu</strong>
              )}
            </span>
            <ChevronDown aria-hidden="true" />
          </button>
        ) : (
          <div className="draft-score-metric">
            {hasScore ? (
              <>
                <span>Güven skoru</span>
                <strong>{draft.combined_score}</strong>
                <span>/100</span>
                <span className="sr-only">Güven skoru: {draft.combined_score}/100</span>
              </>
            ) : (
              <strong>Taslak durumu</strong>
            )}
          </div>
        )}
        <div className="draft-meta-actions">
          {draftId && (
            <details className="draft-download-menu">
              <summary>
                <FileDown aria-hidden="true" />
                İndir
              </summary>
              <div role="menu" aria-label="İndirme formatı">
                <button
                  type="button"
                  role="menuitem"
                  onClick={(event) => {
                    event.currentTarget.closest("details")?.removeAttribute("open");
                    void draftService.export(draftId, "docx", persistedDraftQuery.data?.version);
                  }}
                >
                  <FileText aria-hidden="true" />
                  Word (.docx)
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={(event) => {
                    event.currentTarget.closest("details")?.removeAttribute("open");
                    void draftService.export(draftId, "pdf", persistedDraftQuery.data?.version);
                  }}
                >
                  <FileDown aria-hidden="true" />
                  PDF
                </button>
              </div>
            </details>
          )}
          <div className="draft-meta-statuses">
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
            {hasScore && !isRejected && !isReviseExhausted && (
              <span className="draft-meta-chip draft-meta-success">
                <CheckCircle2 size={13} />
                Hazır
              </span>
            )}
          </div>
        </div>
      </header>

      <ApiErrorNotice error={updateDestinationMutation.error} />

      {expanded && (
        <div className="draft-meta-body" id={detailId}>
          {appliedRules.length > 0 && (
            <section className="draft-meta-detail">
              <h4>Skor dökümü ({appliedRules.length})</h4>
              <div className="draft-meta-detail-content">
                {appliedRules.map((rule) => (
                  <p key={rule.rule_id}>
                    {rule.label}
                    {rule.occurrences > 1 ? ` (×${rule.occurrences})` : ""}
                    {rule.penalty_applied > 0 ? ` — -${rule.penalty_applied} puan` : ""}
                  </p>
                ))}
              </div>
            </section>
          )}

          {hasControlNotes && (
            <section className="draft-meta-detail">
              <h4>Kontrol notları</h4>
              <div className="draft-meta-detail-content">
                <p>{draft.evaluation_notes}</p>
              </div>
            </section>
          )}

          {(routedUnit || draftId) && (
            <div className="draft-routing-row">
              {routedUnit && (
                <span className="draft-meta-chip draft-routing-value">
                  <Route size={14} />
                  {destinationOverridden ? "Hedef birim" : "Önerilen birim"}: {routedUnit}
                  {alternativeUnits.length > 0 && !destinationOverridden
                    ? ` · Alternatif: ${alternativeUnits.join(", ")}`
                    : ""}
                </span>
              )}
              {draftId && (
                <UnitPicker
                  currentDestination={routedUnit ?? null}
                  saving={updateDestinationMutation.isPending}
                  onSave={(destination) => updateDestinationMutation.mutate(destination)}
                />
              )}
            </div>
          )}

          {changelogSummary && (
            <p className="draft-meta-change-summary">
              <strong>Değişiklik özeti:</strong> {changelogSummary}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
