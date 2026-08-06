import { FileText, X } from "lucide-react";
import type { DocumentMetadata } from "../../types/documents";

export function DocumentSelector({
  documents,
  selected,
  onSelect,
  onClear,
}: {
  documents: DocumentMetadata[];
  selected: DocumentMetadata | null;
  onSelect: (document: DocumentMetadata) => void;
  onClear: () => void;
}) {
  return (
    <div className="document-selector">
      {selected ? (
        <div className="selected-document">
          <FileText size={16} />
          <span className="selected-document-copy">
            <small className="selected-document-label">Seçili evrak</small>
            <strong className="selected-document-title" title={selected.file_name}>
              {selected.file_name}
            </strong>
          </span>
          <button
            type="button"
            className="icon-button"
            onClick={onClear}
            aria-label="Evrak seçimini kaldır"
          >
            <X size={16} />
          </button>
        </div>
      ) : (
        <select
          value=""
          aria-label="Sohbette kullanılacak evrak"
          onChange={(event) => {
            const item = documents.find(
              (document) => document.storage_path === event.target.value,
            );
            if (item) onSelect(item);
          }}
        >
          <option value="">Evrak seçilmedi</option>
          {documents.map((document) => (
            <option key={document.storage_path} value={document.storage_path}>
              {document.file_name}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
