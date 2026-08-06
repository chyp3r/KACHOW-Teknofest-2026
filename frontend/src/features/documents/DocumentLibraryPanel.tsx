import { ArrowRight, FileText, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { EmptyState } from "../../components/EmptyState";
import type { DocumentMetadata } from "../../types/documents";
import { DocumentUploader } from "./DocumentUploader";

interface DocumentLibraryPanelProps {
  documents: DocumentMetadata[];
  selected: DocumentMetadata | null;
  loading: boolean;
  uploading: boolean;
  error: string | null;
  onUpload: (file: File) => Promise<void>;
  onSelect: (document: DocumentMetadata) => void;
  onViewDetails: () => void;
}

export function DocumentLibraryPanel({
  documents,
  selected,
  loading,
  uploading,
  error,
  onUpload,
  onSelect,
  onViewDetails,
}: DocumentLibraryPanelProps) {
  const [query, setQuery] = useState("");
  const filteredDocuments = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase("tr-TR");
    if (!normalizedQuery) return documents;

    return documents.filter((document) =>
      `${document.file_name} ${document.summary} ${document.document_type_label}`
        .toLocaleLowerCase("tr-TR")
        .includes(normalizedQuery),
    );
  }, [documents, query]);

  return (
    <section
      id="document-library-panel"
      className="sidebar-document-library"
      aria-label="Evrak Kütüphanesi hızlı erişim"
    >
      {error && (
        <div className="notice danger" role="alert">
          {error}
        </div>
      )}

      <DocumentUploader uploading={uploading} onUpload={onUpload} />

      <section
        className="quick-document-list"
        aria-labelledby="quick-list-title"
      >
        <div className="section-heading">
          <div>
            <h2 id="quick-list-title">Kayıtlı evraklar</h2>
            <p>{documents.length} evrak kütüphanede bulunuyor.</p>
          </div>
        </div>
        <label className="search-field">
          <Search size={15} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Evraklarda ara"
            aria-label="Evraklarda ara"
          />
        </label>

        {loading ? (
          <div className="library-loading">Evraklar yükleniyor…</div>
        ) : filteredDocuments.length === 0 ? (
          <EmptyState
            icon={FileText}
            title="Evrak bulunamadı"
            description={
              query
                ? "Arama ölçütünü değiştirin."
                : "İlk evrakınızı yukarıdaki alandan yükleyin."
            }
          />
        ) : (
          <ul className="quick-document-items">
            {filteredDocuments.map((document) => {
              const isSelected =
                selected?.storage_path === document.storage_path;
              return (
                <li key={document.storage_path}>
                  <button
                    className={isSelected ? "is-selected" : ""}
                    aria-pressed={isSelected}
                    onClick={() => onSelect(document)}
                  >
                    <span className="quick-document-icon">
                      <FileText size={15} />
                    </span>
                    <span className="quick-document-copy">
                      <strong>{document.file_name}</strong>
                      <small>
                        {document.document_type_label || document.document_type}
                      </small>
                    </span>
                    <span className="quick-document-state">
                      {isSelected ? "Seçili" : "Seç"}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <button
        className="button button-secondary library-details-button"
        onClick={onViewDetails}
      >
        Detaylı görüntüle
        <ArrowRight size={15} />
      </button>
    </section>
  );
}
