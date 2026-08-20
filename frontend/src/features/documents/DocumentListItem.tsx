import {
  FilePenLine,
  FileSearch,
  FileText,
  MessageSquare,
  MoreHorizontal,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { Link } from "react-router-dom";
import { StatusBadge } from "../../components/StatusBadge";
import type { DocumentMetadata } from "../../types/documents";

function compliance(document: DocumentMetadata) {
  if (document.analyzed === false) {
    return { label: "Analiz bekliyor", tone: "pending" as const };
  }
  const compliant = document.compliance_status.toLocaleLowerCase("tr-TR") === "compliant";
  return {
    label: compliant ? "Onaylandı" : "İnceleme gerekli",
    tone: compliant ? "success" as const : "warning" as const,
  };
}

export function DocumentActionsMenu({
  document,
  onSelect,
  onViewAnalysis,
  onAnalyze,
  analyzing,
  onDelete,
}: {
  document: DocumentMetadata;
  onSelect: () => void;
  onViewAnalysis: () => void;
  onAnalyze?: () => void;
  analyzing?: boolean;
  onDelete?: () => void;
}) {
  const analyzed = document.analyzed !== false;
  return (
    <details className="document-actions-menu">
      <summary aria-label={`${document.file_name} için işlemler`} title="İşlemler">
        <MoreHorizontal aria-hidden="true" />
      </summary>
      <div className="document-actions-popover" role="menu">
        <Link to="/chats" role="menuitem" onClick={onSelect}><MessageSquare />Sohbette aç</Link>
        {analyzed && (
          <button type="button" role="menuitem" onClick={onViewAnalysis}>
            <FileSearch />Analizi görüntüle
          </button>
        )}
        {analyzed && <Link to="/drafts" role="menuitem" onClick={onSelect}><FilePenLine />Taslak hazırla</Link>}
        {onAnalyze && (
          <button type="button" role="menuitem" disabled={analyzing} onClick={onAnalyze}>
            <RefreshCw />{analyzed ? "Yeniden analiz et" : "Analiz et"}
          </button>
        )}
        {onDelete && <span className="document-menu-divider" aria-hidden="true" />}
        {onDelete && (
          <button type="button" role="menuitem" className="danger-text" onClick={onDelete}>
            <Trash2 />Sil
          </button>
        )}
      </div>
    </details>
  );
}

export function DocumentListItem({
  document,
  expanded,
  detailId,
  onToggle,
  onViewAnalysis,
  onAnalyze,
  analyzing,
  onDelete,
}: {
  document: DocumentMetadata;
  expanded: boolean;
  detailId: string;
  onToggle: () => void;
  onViewAnalysis: () => void;
  onAnalyze?: () => void;
  analyzing?: boolean;
  onDelete?: () => void;
}) {
  const status = compliance(document);
  const analyzed = document.analyzed !== false;
  const type = document.document_type_label || document.document_type || "Belge";
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
          <span title={document.summary || undefined}>{document.summary || (analyzed ? "Özet bulunmuyor." : "Henüz analiz edilmedi.")}</span>
        </span>
        <span className="document-item-metadata">
          <span>{type} · {new Intl.DateTimeFormat("tr-TR", { dateStyle: "medium" }).format(new Date(document.upload_time))}</span>
          <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
        </span>
      </button>
      <DocumentActionsMenu
        document={document}
        onSelect={onToggle}
        onViewAnalysis={onViewAnalysis}
        onAnalyze={onAnalyze}
        analyzing={analyzing}
        onDelete={onDelete}
      />
    </div>
  );
}
