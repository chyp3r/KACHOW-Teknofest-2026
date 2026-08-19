import { Plus, X } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "../components/PageHeader";
import { DocumentTable } from "../features/documents/DocumentTable";
import { DocumentUploader } from "../features/documents/DocumentUploader";
import type { DocumentAnalysis, DocumentMetadata, DocumentText, EvrakFields, KnowledgeGraph } from "../types/documents";
import { Button } from "../components/Button";
import { Alert } from "../components/Surface";

export function DocumentsPage({
  documents,
  selected,
  analysis,
  loading,
  uploading,
  updatingFields,
  deletingDocument,
  error,
  onUpload,
  onUpdateFields,
  onDeleteDocument,
  onSelect,
  onCloseDocument,
  onGenerateDetailedSummary,
  generatingDetailedSummary,
  documentGraph,
  loadingDocumentGraph,
  documentText,
  onSaveText,
  savingText,
  onReextract,
  reextracting,
}: {
  documents: DocumentMetadata[];
  selected: DocumentMetadata | null;
  analysis: DocumentAnalysis | null;
  loading: boolean;
  uploading: boolean;
  updatingFields?: boolean;
  deletingDocument?: boolean;
  error: string | null;
  onUpload: (file: File) => Promise<void>;
  onUpdateFields?: (storagePath: string, fields: EvrakFields) => Promise<void>;
  onDeleteDocument?: (storagePath: string) => Promise<void>;
  onSelect: (document: DocumentMetadata) => void;
  onCloseDocument?: () => void;
  onGenerateDetailedSummary?: (storagePath: string) => Promise<void>;
  generatingDetailedSummary?: boolean;
  documentGraph?: KnowledgeGraph | null;
  loadingDocumentGraph?: boolean;
  documentText?: DocumentText | null;
  onSaveText?: (storagePath: string, pages: string[]) => Promise<void>;
  savingText?: boolean;
  onReextract?: (storagePath: string) => Promise<void>;
  reextracting?: boolean;
}) {
  const [uploadOpen, setUploadOpen] = useState(false);

  const upload = async (file: File) => {
    await onUpload(file);
    setUploadOpen(false);
  };

  return (
    <div className="page page-scroll documents-page">
      <PageHeader
        title="Evrak Kütüphanesi"
        primaryAction={(
          <Button
            variant={uploadOpen ? "outline" : "primary"}
            aria-controls="document-upload-panel"
            aria-expanded={uploadOpen}
            onClick={() => setUploadOpen((current) => !current)}
            leadingIcon={uploadOpen ? <X /> : <Plus />}
          >
            {uploadOpen ? "Yüklemeyi kapat" : "Evrak yükle"}
          </Button>
        )}
      />

      {error && (
        <Alert variant="error">{error}</Alert>
      )}

      {uploadOpen && (
        <div id="document-upload-panel" className="document-upload-panel">
          <DocumentUploader uploading={uploading} onUpload={upload} />
        </div>
      )}

      <DocumentTable
        documents={documents}
        selected={selected}
        analysis={analysis}
        loading={loading}
        updatingFields={updatingFields}
        deletingDocument={deletingDocument}
        onSelect={onSelect}
        onClose={onCloseDocument}
        onUpdateFields={onUpdateFields}
        onDeleteDocument={onDeleteDocument}
        onGenerateDetailedSummary={onGenerateDetailedSummary}
        generatingDetailedSummary={generatingDetailedSummary}
        documentGraph={documentGraph}
        loadingDocumentGraph={loadingDocumentGraph}
        documentText={documentText}
        onSaveText={onSaveText}
        savingText={savingText}
        onReextract={onReextract}
        reextracting={reextracting}
      />
    </div>
  );
}
