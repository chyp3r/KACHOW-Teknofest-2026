import {
  ArrowDownAZ,
  FileText,
  Search,
} from "lucide-react";
import { useMemo, useState } from "react";
import { ConfirmationDialog } from "../../components/ConfirmationDialog";
import { EmptyState } from "../../components/EmptyState";
import type { DocumentAnalysis, DocumentMetadata, DocumentText, EvrakFields } from "../../types/documents";
import { DocumentAnalysisPanel } from "./DocumentAnalysisPanel";
import { Button } from "../../components/Button";
import { Input, Select } from "../../components/FormControls";
import { SectionHeader } from "../../components/SectionHeader";
import { Card, Spinner } from "../../components/Surface";
import { DocumentListItem } from "./DocumentListItem";

export function DocumentTable({
  documents,
  selected,
  analysis,
  loading,
  updatingFields,
  onSelect,
  onClose,
  onUpdateFields,
  onDeleteDocument,
  deletingDocument,
  onGenerateDetailedSummary,
  generatingDetailedSummary,
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
  updatingFields?: boolean;
  onSelect: (document: DocumentMetadata) => void;
  onClose?: () => void;
  onUpdateFields?: (storagePath: string, fields: EvrakFields) => Promise<void>;
  onDeleteDocument?: (storagePath: string) => Promise<void>;
  deletingDocument?: boolean;
  onGenerateDetailedSummary?: (storagePath: string) => Promise<void>;
  generatingDetailedSummary?: boolean;
  documentText?: DocumentText | null;
  onSaveText?: (storagePath: string, pages: string[]) => Promise<void>;
  savingText?: boolean;
  onReextract?: (storagePath: string) => Promise<void>;
  reextracting?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [pendingDeletePath, setPendingDeletePath] = useState<string | null>(null);
  const [type, setType] = useState("all");
  const [ascending, setAscending] = useState(false);
  const types = useMemo(
    () => [
      ...new Set(
        documents.map((item) => item.document_type_label || item.document_type),
      ),
    ],
    [documents],
  );
  const filtered = useMemo(
    () =>
      documents
        .filter((item) => {
          const matchesQuery = `${item.file_name} ${item.summary}`
            .toLocaleLowerCase("tr-TR")
            .includes(query.toLocaleLowerCase("tr-TR"));
          return (
            matchesQuery &&
            (type === "all" ||
              (item.document_type_label || item.document_type) === type)
          );
        })
        .sort(
          (a, b) =>
            (new Date(a.upload_time).getTime() -
              new Date(b.upload_time).getTime()) *
            (ascending ? 1 : -1),
        ),
    [ascending, documents, query, type],
  );

  return (
    <Card className="document-list-card" role="region" aria-label="Kayıtlı evraklar">
      <SectionHeader className="document-list-heading" title="Kayıtlı evraklar" description={`${documents.length} evrak kütüphanede bulunuyor.`} />
      <div className="table-toolbar document-list-toolbar">
        <Input
            fieldClassName="search-field"
            leadingIcon={<Search />}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Evraklarda ara"
            aria-label="Evraklarda ara"
          />
        <Select
          value={type}
          onChange={(event) => setType(event.target.value)}
          aria-label="Dosya türüne göre filtrele"
        >
          <option value="all">Tüm türler</option>
          {types.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </Select>
        <Button
          variant="secondary"
          leadingIcon={<ArrowDownAZ />}
          onClick={() => setAscending((value) => !value)}
        >
          {ascending ? "Eskiden yeniye" : "Yeniden eskiye"}
        </Button>
      </div>

      {loading && documents.length === 0 ? (
        <div className="table-loading"><Spinner label="Evraklar yükleniyor" />Evraklar yükleniyor…</div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="Evrak bulunamadı"
          description={
            query || type !== "all"
              ? "Arama veya filtre ölçütlerini değiştirin."
              : "Sağ üstteki Evrak yükle düğmesiyle ilk evrakınızı yükleyin."
          }
        />
      ) : (
        <ul className="document-accordion-list">
          {filtered.map((item) => {
            const expanded = selected?.storage_path === item.storage_path;
            const detailId = `document-detail-${item.storage_path.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
            return (
              <li key={item.storage_path} className={expanded ? "is-expanded" : undefined}>
                <DocumentListItem
                  document={item}
                  detailId={detailId}
                  expanded={expanded}
                  onToggle={() => {
                    if (expanded) onClose?.();
                    else onSelect(item);
                  }}
                  onDelete={
                    onDeleteDocument ? () => setPendingDeletePath(item.storage_path) : undefined
                  }
                />

                {expanded && (
                  <div id={detailId} className="document-accordion-detail">
                    <p className="document-expanded-summary"><strong>Özet</strong><span>{item.summary || "Özet bulunmuyor."}</span></p>
                    {loading && !analysis ? (
                      <div className="centered-state"><Spinner label="Analiz ayrıntıları yükleniyor" />Analiz ayrıntıları yükleniyor…</div>
                    ) : (
                      <DocumentAnalysisPanel
                        analysis={analysis}
                        saving={updatingFields}
                        onSave={
                          onUpdateFields && analysis
                            ? (fields) => onUpdateFields(analysis.storage_path, fields)
                            : undefined
                        }
                        generatingDetailedSummary={generatingDetailedSummary}
                        onGenerateDetailedSummary={
                          onGenerateDetailedSummary && analysis
                            ? () => onGenerateDetailedSummary(analysis.storage_path)
                            : undefined
                        }
                        documentText={documentText}
                        savingText={savingText}
                        onSaveText={
                          onSaveText && analysis
                            ? (pages) => onSaveText(analysis.storage_path, pages)
                            : undefined
                        }
                        reextracting={reextracting}
                        onReextract={
                          onReextract && analysis
                            ? () => onReextract(analysis.storage_path)
                            : undefined
                        }
                      />
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <ConfirmationDialog
        open={pendingDeletePath !== null}
        title="Evrakı sil"
        description="Bu evrak, analiz sonuçları ve dizinlenmiş içerikleri kalıcı olarak silinecek. Bu işlem geri alınamaz."
        confirmLabel="Sil"
        busy={deletingDocument}
        onConfirm={async () => {
          if (!pendingDeletePath || !onDeleteDocument) return;
          if (selected?.storage_path === pendingDeletePath) onClose?.();
          await onDeleteDocument(pendingDeletePath);
          setPendingDeletePath(null);
        }}
        onCancel={() => setPendingDeletePath(null)}
      />
    </Card>
  );
}
