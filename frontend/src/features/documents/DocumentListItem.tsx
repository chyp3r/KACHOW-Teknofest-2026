import { ChevronDown, ChevronUp, FileText, Trash2 } from "lucide-react";
import { IconButton } from "../../components/Button";
import { StatusBadge } from "../../components/StatusBadge";
import type { DocumentMetadata } from "../../types/documents";

function compliance(document: DocumentMetadata) {
  const compliant = document.compliance_status.toLocaleLowerCase("tr-TR") === "compliant";
  return {
    label: compliant ? "Uygun" : "Kontrol gerekli",
    tone: compliant ? "success" as const : "warning" as const,
  };
}

export function DocumentListItem({
  document,
  expanded,
  detailId,
  onToggle,
  onDelete,
}: {
  document: DocumentMetadata;
  expanded: boolean;
  detailId: string;
  onToggle: () => void;
  onDelete?: () => void;
}) {
  const status = compliance(document);
  const type = document.document_type_label || document.document_type;
  return (
    <div className="document-list-item-shell">
      <button
        type="button"
        className={`document-list-item ${expanded ? "is-selected" : ""}`}
        aria-controls={detailId}
        aria-expanded={expanded}
        onClick={onToggle}
      >
        <span className="document-item-icon" aria-hidden="true"><FileText /></span>
        <span className="document-item-copy">
          <strong title={document.file_name}>{document.file_name}</strong>
          <span title={document.summary || undefined}>{document.summary || "Özet bulunmuyor."}</span>
        </span>
        <span className="document-item-metadata">
          <span className="document-item-field">
            <small>Tür</small>
            <span title={type}>{type}</span>
          </span>
          <span className="document-item-field">
            <small>Tarih</small>
            <time dateTime={document.upload_time}>{new Intl.DateTimeFormat("tr-TR", { dateStyle: "medium" }).format(new Date(document.upload_time))}</time>
          </span>
          <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
          <span className="document-item-action" aria-hidden="true">{expanded ? <ChevronUp /> : <ChevronDown />}</span>
        </span>
      </button>
      {onDelete && (
        <IconButton
          className="document-list-item-delete danger-text"
          icon={<Trash2 />}
          aria-label="Evrakı sil"
          variant="ghost"
          onClick={onDelete}
        />
      )}
    </div>
  );
}
