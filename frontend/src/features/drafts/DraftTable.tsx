import { ChevronDown, ChevronUp, FilePenLine } from "lucide-react";
import type { KeyboardEvent, ReactNode } from "react";
import type { PersistedDraft } from "../../types/drafts";

export function DraftTable({
  drafts,
  activeDraftId,
  titleFor,
  onToggle,
  renderDetail,
  renderRowActions,
}: {
  drafts: PersistedDraft[];
  activeDraftId?: string;
  titleFor: (draft: PersistedDraft) => string;
  onToggle: (draft: PersistedDraft, expanded: boolean) => void;
  renderDetail: (draft: PersistedDraft, detailId: string) => ReactNode;
  renderRowActions?: (draft: PersistedDraft) => ReactNode;
}) {
  const activate = (event: KeyboardEvent<HTMLDivElement>, draft: PersistedDraft, expanded: boolean) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onToggle(draft, expanded);
  };

  return (
    <div className="draft-table" role="table" aria-label="Oluşturulan taslaklar">
      <div className="draft-table-header" role="row">
        {['Taslak', 'Hedef birim', 'Sürüm', 'Güncellendi', 'İşlem'].map((label) => (
          <span key={label} role="columnheader">{label}</span>
        ))}
      </div>
      <div role="rowgroup">
        {drafts.map((draft) => {
          const expanded = draft.id === activeDraftId;
          const detailId = `draft-detail-${draft.id}`;
          const title = titleFor(draft);
          const destination = draft.destination || "Hedef belirtilmedi";
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
                <span className="draft-table-cell" role="cell" title={destination}><span className="draft-cell-label">Hedef birim</span><span className="draft-cell-value">{destination}</span></span>
                <span className="draft-table-cell draft-compact-cell" role="cell"><span className="draft-cell-label">Sürüm</span><span className="draft-cell-value">v{draft.version}</span></span>
                <span className="draft-table-cell draft-date-cell" role="cell"><span className="draft-cell-label">Güncellendi</span><time dateTime={draft.updated_at}>{new Intl.DateTimeFormat("tr-TR", { dateStyle: "short" }).format(new Date(draft.updated_at))}</time></span>
                <span className="draft-table-action" role="cell" onClick={(event) => event.stopPropagation()}>
                  {renderRowActions?.(draft)}
                  <span aria-hidden="true">{expanded ? <ChevronUp /> : <ChevronDown />}</span>
                </span>
              </div>
              {expanded && renderDetail(draft, detailId)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
