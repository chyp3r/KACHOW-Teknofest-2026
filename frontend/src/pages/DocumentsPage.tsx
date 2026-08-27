import { Inbox, Library, Plus, Send, X } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "../components/PageHeader";
import { DocumentTable } from "../features/documents/DocumentTable";
import { DocumentUploader } from "../features/documents/DocumentUploader";
import type { DocumentAnalysis, DocumentMetadata, DocumentText, EvrakFields, KnowledgeGraph } from "../types/documents";
import { Button } from "../components/Button";
import { Alert } from "../components/Surface";
import { Tabs } from "../components/Tabs";
import { IncomingDocumentsPanel } from "../features/documents/IncomingDocumentsPanel";
import { PoolPushDialog } from "../features/documents/PoolPushDialog";

export function DocumentsPage({
  documents,
  selected,
  analysis,
  loading,
  uploading,
  updatingFields,
  analyzingStoragePath,
  deletingDocument,
  error,
  onUpload,
  onUpdateFields,
  onAnalyzeDocument,
  onDeleteDocument,
  onSelect,
  onCloseDocument,
  onGenerateDetailedSummary,
  generatingDetailedSummary,
  generatingDetailedSummaryPath,
  onGenerateDetailedAnalysis,
  generatingDetailedAnalysis,
  generatingDetailedAnalysisPath,
  documentGraph,
  loadingDocumentGraph,
  documentText,
  onSaveText,
  savingText,
  canPush = false,
  showUploader = false,
}: {
  documents: DocumentMetadata[];
  selected: DocumentMetadata | null;
  analysis: DocumentAnalysis | null;
  loading: boolean;
  uploading: boolean;
  updatingFields?: boolean;
  analyzingStoragePath?: string | null;
  deletingDocument?: boolean;
  error: string | null;
  onUpload: (file: File) => Promise<void>;
  onUpdateFields?: (storagePath: string, fields: EvrakFields) => Promise<void>;
  onAnalyzeDocument?: (storagePath: string) => Promise<unknown>;
  onDeleteDocument?: (storagePath: string) => Promise<void>;
  onSelect: (document: DocumentMetadata) => void;
  onCloseDocument?: () => void;
  onGenerateDetailedSummary?: (storagePath: string) => Promise<void>;
  generatingDetailedSummary?: boolean;
  generatingDetailedSummaryPath?: string | null;
  onGenerateDetailedAnalysis?: (storagePath: string) => Promise<void>;
  generatingDetailedAnalysis?: boolean;
  generatingDetailedAnalysisPath?: string | null;
  documentGraph?: KnowledgeGraph | null;
  loadingDocumentGraph?: boolean;
  documentText?: DocumentText | null;
  onSaveText?: (storagePath: string, pages: string[]) => Promise<void>;
  savingText?: boolean;
  canPush?: boolean;
  showUploader?: boolean;
}) {
  const [uploadOpen, setUploadOpen] = useState(false);
  const [tab, setTab] = useState<"library" | "incoming">("library");
  const [pushOpen, setPushOpen] = useState(false);

  const upload = async (file: File) => {
    await onUpload(file);
    setUploadOpen(false);
  };
  const openUpload = () => {
    setTab("library");
    setUploadOpen(true);
  };

  return (
    <div className="page page-scroll documents-page">
      <PageHeader
        title="Evrak Kütüphanesi"
        description="Kurum içi ve dışı tüm evraklarınıza tek yerden erişin, yönetin ve paylaşın."
        secondaryActions={tab === "library" && canPush && selected ? <Button variant="outline" leadingIcon={<Send />} onClick={() => setPushOpen(true)}>Havuza gönder</Button> : undefined}
        primaryAction={(
          <Button
            variant={uploadOpen ? "outline" : "primary"}
            aria-controls="document-upload-panel"
            aria-expanded={uploadOpen}
            onClick={() => tab === "library" ? setUploadOpen((current) => !current) : openUpload()}
            leadingIcon={uploadOpen ? <X /> : <Plus />}
          >
            {uploadOpen ? "Yüklemeyi kapat" : "Evrak yükle"}
          </Button>
        )}
      />

      <Tabs label="Evrak görünümleri" active={tab} onChange={setTab} items={[{ id: "library", label: "Kütüphane", icon: <Library /> }, { id: "incoming", label: "Gelen Evraklar", icon: <Inbox /> }]} />

      {error && (
        <Alert variant="error">{error}</Alert>
      )}

      {tab === "library" && uploadOpen && (
        <div id="document-upload-panel" className="document-upload-panel">
          <DocumentUploader uploading={uploading} onUpload={upload} />
        </div>
      )}

      {tab === "library" ? <DocumentTable
        documents={documents}
        selected={selected}
        analysis={analysis}
        loading={loading}
        updatingFields={updatingFields}
        analyzingStoragePath={analyzingStoragePath}
        deletingDocument={deletingDocument}
        onSelect={onSelect}
        onClose={onCloseDocument}
        onUpdateFields={onUpdateFields}
        onAnalyzeDocument={onAnalyzeDocument}
        onDeleteDocument={onDeleteDocument}
        onGenerateDetailedSummary={onGenerateDetailedSummary}
        generatingDetailedSummary={generatingDetailedSummary}
        generatingDetailedSummaryPath={generatingDetailedSummaryPath}
        onGenerateDetailedAnalysis={onGenerateDetailedAnalysis}
        generatingDetailedAnalysis={generatingDetailedAnalysis}
        generatingDetailedAnalysisPath={generatingDetailedAnalysisPath}
        documentGraph={documentGraph}
        loadingDocumentGraph={loadingDocumentGraph}
        documentText={documentText}
        onSaveText={onSaveText}
        savingText={savingText}
        showUploader={showUploader}
      /> : <IncomingDocumentsPanel />}
      {canPush && selected && <PoolPushDialog open={pushOpen} documentId={selected.storage_path} onClose={() => setPushOpen(false)} />}
    </div>
  );
}
