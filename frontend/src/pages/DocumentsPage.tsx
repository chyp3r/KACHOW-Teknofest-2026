import { PageHeader } from "../components/PageHeader";
import { DocumentAnalysisPanel } from "../features/documents/DocumentAnalysisPanel";
import { DocumentTable } from "../features/documents/DocumentTable";
import { DocumentUploader } from "../features/documents/DocumentUploader";
import type { DocumentAnalysis, DocumentMetadata } from "../types/documents";

export function DocumentsPage({
  documents,
  selected,
  analysis,
  loading,
  uploading,
  error,
  onUpload,
  onSelect,
}: {
  documents: DocumentMetadata[];
  selected: DocumentMetadata | null;
  analysis: DocumentAnalysis | null;
  loading: boolean;
  uploading: boolean;
  error: string | null;
  onUpload: (file: File) => Promise<void>;
  onSelect: (document: DocumentMetadata) => void;
}) {
  return (
    <div className="page page-scroll">
      <PageHeader
        title="Evrak Kütüphanesi"
        description="Evrakları yükleyin, analiz sonuçlarını inceleyin ve sohbetlerde kullanmak üzere seçin."
      />
      {error && (
        <div className="notice danger" role="alert">
          {error}
        </div>
      )}
      <div className="documents-layout">
        <div>
          <DocumentUploader uploading={uploading} onUpload={onUpload} />
          <DocumentTable
            documents={documents}
            selected={selected}
            loading={loading}
            onSelect={onSelect}
          />
        </div>
        <DocumentAnalysisPanel analysis={analysis} />
      </div>
    </div>
  );
}
