import { ChevronDown, ChevronUp, FilePenLine } from "lucide-react";
import type { KeyboardEvent, ReactNode } from "react";
import { StatusBadge, type StatusTone } from "../../components/StatusBadge";
import type { PersistedDraft } from "../../types/drafts";

function approval(draft: PersistedDraft): { label: string; tone: StatusTone } {
  if (draft.requires_human_approval) return { label: "İnsan onayı", tone: "warning" };
  const normalizedStatus = draft.status?.toLocaleLowerCase("tr-TR");
  if (normalizedStatus === "failed") return { label: "Başarısız", tone: "danger" };
  if (normalizedStatus === "ready" || normalizedStatus === "completed") return { label: "Hazır", tone: "success" };
  return { label: normalizedStatus?.replace(/_/g, " ") || "Bekliyor", tone: "neutral" };
}

export function DraftTable({
  drafts,
  activeDraftId,
  titleFor,
  sourceFor,
  onToggle,
  renderDetail,
}: {
  drafts: PersistedDraft[];
  activeDraftId?: string;
  titleFor: (draft: PersistedDraft) => string;
  sourceFor: (draft: PersistedDraft) => string;
  onToggle: (draft: PersistedDraft, expanded: boolean) => void;
  renderDetail: (draft: PersistedDraft, detailId: string) => ReactNode;
}) {
  const activate = (event: KeyboardEvent<HTMLDivElement>, draft: PersistedDraft, expanded: boolean) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onToggle(draft, expanded);
  };

  return (
    <div className="draft-table" role="table" aria-label="Oluşturulan taslaklar">
      <div className="draft-table-header" role="row">
        {['Taslak', 'Durum / onay', 'Hedef birim', 'Kaynak evrak', 'Sürüm', 'Güncellendi', 'İşlem'].map((label) => (
          <span key={label} role="columnheader">{label}</span>
        ))}
      </div>
      <div role="rowgroup">
        {drafts.map((draft) => {
          const expanded = draft.id === activeDraftId;
          const detailId = `draft-detail-${draft.id}`;
          const status = approval(draft);
          const title = titleFor(draft);
          const destination = draft.destination || "Hedef belirtilmedi";
          const source = sourceFor(draft);
          return (
            <div key={draft.id} className={`draft-table-record ${expanded ? "is-expanded" : ""}`}>
              <div
                className="draft-table-row"
                role="row"
                tabIndex={0}
                aria-controls={detailId}
                aria-expanded={expanded}
                onClick={() => onToggle(draft, expanded)}
                onKeyDown={(event) => activate(event, draft, expanded)}
              >
                <span className="draft-table-cell draft-title-cell" role="cell" title={title}>
                  <span className="draft-cell-label">Taslak</span>
                  <span className="draft-title-value"><span className="draft-table-icon" aria-hidden="true"><FilePenLine /></span><strong>{title}</strong></span>
                </span>
                <span className="draft-table-cell" role="cell"><span className="draft-cell-label">Durum / onay</span><StatusBadge tone={status.tone}>{status.label}</StatusBadge></span>
                <span className="draft-table-cell" role="cell" title={destination}><span className="draft-cell-label">Hedef birim</span><span className="draft-cell-value">{destination}</span></span>
                <span className="draft-table-cell" role="cell" title={source}><span className="draft-cell-label">Kaynak evrak</span><span className="draft-cell-value">{source}</span></span>
                <span className="draft-table-cell draft-compact-cell" role="cell"><span className="draft-cell-label">Sürüm</span><span className="draft-cell-value">v{draft.version}</span></span>
                <span className="draft-table-cell draft-date-cell" role="cell"><span className="draft-cell-label">Güncellendi</span><time dateTime={draft.updated_at}>{new Intl.DateTimeFormat("tr-TR", { dateStyle: "short" }).format(new Date(draft.updated_at))}</time></span>
                <span className="draft-table-action" role="cell" aria-hidden="true">{expanded ? <ChevronUp /> : <ChevronDown />}</span>
              </div>
              {expanded && renderDetail(draft, detailId)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
