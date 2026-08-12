import {
  ArrowDownAZ,
  FileText,
  Search,
} from "lucide-react";
import { useMemo, useState } from "react";
import { EmptyState } from "../../components/EmptyState";
import type { DocumentAnalysis, DocumentMetadata, EvrakFields } from "../../types/documents";
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
}: {
  documents: DocumentMetadata[];
  selected: DocumentMetadata | null;
  analysis: DocumentAnalysis | null;
  loading: boolean;
  updatingFields?: boolean;
  onSelect: (document: DocumentMetadata) => void;
  onClose?: () => void;
  onUpdateFields?: (storagePath: string, fields: EvrakFields) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
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
                      />
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
