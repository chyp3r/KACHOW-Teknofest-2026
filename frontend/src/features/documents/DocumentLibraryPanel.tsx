import { ArrowRight, FileText, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { EmptyState } from "../../components/EmptyState";
import type { DocumentMetadata } from "../../types/documents";
import { DocumentUploader } from "./DocumentUploader";
import { Button } from "../../components/Button";
import { Input } from "../../components/FormControls";
import { ListRow } from "../../components/ListRow";
import { SectionHeader } from "../../components/SectionHeader";
import { Alert, Spinner } from "../../components/Surface";

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
        <Alert variant="error">{error}</Alert>
      )}

      <DocumentUploader uploading={uploading} onUpload={onUpload} />

      <section
        className="quick-document-list"
        aria-labelledby="quick-list-title"
      >
        <SectionHeader title="Kayıtlı evraklar" description={`${documents.length} evrak kütüphanede bulunuyor.`} />
        <Input
            fieldClassName="search-field"
            leadingIcon={<Search />}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Evraklarda ara"
            aria-label="Evraklarda ara"
          />

        {loading ? (
          <div className="library-loading"><Spinner label="Evraklar yükleniyor" />Evraklar yükleniyor…</div>
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
                  <ListRow
                    className={isSelected ? "is-selected" : ""}
                    aria-pressed={isSelected}
                    onClick={() => onSelect(document)}
                    selected={isSelected}
                    leading={<FileText />}
                    primary={document.file_name}
                    secondary={document.document_type_label || document.document_type}
                    status={<span className="quick-document-state">{isSelected ? "Seçili" : "Seç"}</span>}
                  />
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <Button
        variant="secondary"
        className="library-details-button"
        onClick={onViewDetails}
        trailingIcon={<ArrowRight />}
      >
        Detaylı görüntüle
      </Button>
    </section>
  );
}
