import {
  AlertTriangle,
  ArrowLeft,
  ArrowDownAZ,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FilePenLine,
  FileSearch,
  FileText,
  MessageSquare,
  Pencil,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Button, IconButton } from "../../components/Button";
import { ConfirmationDialog } from "../../components/ConfirmationDialog";
import { EmptyState } from "../../components/EmptyState";
import { Input, Select, Textarea } from "../../components/FormControls";
import { StatusBadge } from "../../components/StatusBadge";
import type { DocumentAnalysis, DocumentMetadata, DocumentText, EvrakFields, KnowledgeGraph } from "../../types/documents";
import { DocumentAnalysisPanel } from "./DocumentAnalysisPanel";
import { Button } from "../../components/Button";
import { SectionHeader } from "../../components/SectionHeader";
import { Card, Spinner } from "../../components/Surface";
import { Tabs } from "../../components/Tabs";
import type {
  DocumentAnalysis,
  DocumentMetadata,
  DocumentText,
  EvrakFields,
  KnowledgeGraph,
} from "../../types/documents";
import { DocumentAnalysisPanel } from "./DocumentAnalysisPanel";
import { DocumentActionsMenu, DocumentListItem } from "./DocumentListItem";

type DetailTab = "summary" | "analysis" | "text" | "details";
type StatusFilter = "all" | "analyzed" | "pending" | "attention";
type DateFilter = "all" | "week" | "month";

const PAGE_SIZE = 10;

const FIELD_LABELS: Partial<Record<keyof EvrakFields, string>> = {
  sayi: "Sayı",
  tarih: "Belge tarihi",
  konu: "Konu",
  muhatap: "Muhatap",
  gonderen_kurum: "Gönderen kurum",
  imza_sahibi: "İmza sahibi",
  imza_unvani: "İmza unvanı",
  gizlilik_derecesi: "Gizlilik derecesi",
  ivedilik: "İvedilik",
  basvuran_adi: "Başvuran",
  adres: "Adres",
  iletisim: "İletişim",
};

function documentStatus(document: DocumentMetadata, issueCount = 0) {
  if (document.analyzed === false) {
    return { label: "Analiz bekliyor", tone: "pending" as const };
  }
  const compliant = document.compliance_status.toLocaleLowerCase("tr-TR") === "compliant";
  const needsReview = !compliant || issueCount > 0;
  return {
    label: needsReview ? `İnceleme gerekli${issueCount ? ` · ${issueCount} konu` : ""}` : "Onaylandı",
    tone: needsReview ? "warning" as const : "success" as const,
  };
}

function hasValue(value: unknown) {
  return Array.isArray(value) ? value.length > 0 : value !== null && value !== undefined && value !== "";
}

function showValue(value: unknown) {
  return Array.isArray(value) ? value.join(", ") : String(value ?? "—");
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("tr-TR", { dateStyle: "medium" }).format(new Date(value));
}

export function DocumentTable({
  documents,
  selected,
  analysis,
  loading,
  updatingFields,
  onSelect,
  onClose,
  onUpdateFields,
  onAnalyzeDocument,
  onDeleteDocument,
  analyzingStoragePath,
  deletingDocument,
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
  updatingFields?: boolean;
  onSelect: (document: DocumentMetadata) => void;
  onClose?: () => void;
  onUpdateFields?: (storagePath: string, fields: EvrakFields) => Promise<void>;
  onAnalyzeDocument?: (storagePath: string) => Promise<unknown>;
  onDeleteDocument?: (storagePath: string) => Promise<void>;
  analyzingStoragePath?: string | null;
  deletingDocument?: boolean;
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
  const [query, setQuery] = useState("");
  const [pendingDeletePath, setPendingDeletePath] = useState<string | null>(null);
  const [type, setType] = useState("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [date, setDate] = useState<DateFilter>("all");
  const [ascending, setAscending] = useState(false);
  const [page, setPage] = useState(1);
  const [detailState, setDetailState] = useState<{ path: string | null; tab: DetailTab }>({ path: null, tab: "summary" });
  const [editingText, setEditingText] = useState(false);
  const [textDraft, setTextDraft] = useState<string[]>([]);
  const [textError, setTextError] = useState<string | null>(null);

  useEffect(() => setPage(1), [query, type, status, date]);

  const detailTab = detailState.path === selected?.storage_path ? detailState.tab : "summary";
  const setDetailTab = (tab: DetailTab) => setDetailState({ path: selected?.storage_path ?? null, tab });
  const selectWithTab = (document: DocumentMetadata, tab: DetailTab) => {
    setDetailState({ path: document.storage_path, tab });
    setEditingText(false);
    setTextError(null);
    onSelect(document);
  };

  const types = useMemo(
    () => [...new Set(documents.map((item) => item.document_type_label || item.document_type).filter(Boolean))],
    [documents],
  );

  const filtered = useMemo(() => {
    const now = Date.now();
    const dateLimit = date === "week" ? 7 : date === "month" ? 30 : null;
    return documents
      .filter((item) => {
        const matchesQuery = `${item.file_name} ${item.summary}`
          .toLocaleLowerCase("tr-TR")
          .includes(query.toLocaleLowerCase("tr-TR"));
        const matchesType = type === "all" || (item.document_type_label || item.document_type) === type;
        const matchesStatus = status === "all"
          || (status === "pending" && item.analyzed === false)
          || (status === "analyzed" && item.analyzed !== false)
          || (status === "attention" && item.analyzed !== false && item.compliance_status.toLocaleLowerCase("tr-TR") !== "compliant");
        const matchesDate = dateLimit === null
          || now - new Date(item.upload_time).getTime() <= dateLimit * 24 * 60 * 60 * 1000;
        return matchesQuery && matchesType && matchesStatus && matchesDate;
      })
      .sort((a, b) => (
        new Date(a.upload_time).getTime() - new Date(b.upload_time).getTime()
      ) * (ascending ? 1 : -1));
  }, [ascending, date, documents, query, status, type]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const visibleDocuments = selected
    ? filtered
    : filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const filtersActive = Boolean(query || type !== "all" || status !== "all" || date !== "all");
  const resetFilters = () => {
    setQuery("");
    setType("all");
    setStatus("all");
    setDate("all");
  };
  const selectedIssueCount = analysis
    ? analysis.missing_fields.length
      + (analysis.guardrail?.requires_human_review ? 1 : 0)
      + (analysis.extraction.used_ocr ? 1 : 0)
    : 0;
  const selectedNeedsReview = selected?.analyzed !== false
    && (selectedIssueCount > 0 || selected?.compliance_status.toLocaleLowerCase("tr-TR") !== "compliant");
  const selectedStatus = selected ? documentStatus(selected, selectedIssueCount) : null;
  const primaryFields = analysis
    ? (Object.entries(FIELD_LABELS) as Array<[keyof EvrakFields, string]>)
      .filter(([key]) => hasValue(analysis.fields[key]))
      .map(([key, label]) => ({ key, label, value: showValue(analysis.fields[key]) }))
    : [];
  const detectedEntities = analysis?.fields.entities?.filter(Boolean) ?? [];
  const analysisIssues = analysis ? [
    ...analysis.missing_fields.map((item) => ({
      title: item.label,
      detail: item.reason || item.mevzuat || "Bu bilgi doğrulanmalı.",
      tone: item.severity.toLocaleLowerCase("tr-TR") === "high" ? "danger" : "warning",
    })),
    ...(analysis.guardrail.requires_human_review
      ? [{ title: "İnsan incelemesi gerekiyor", detail: analysis.guardrail.reasons.join(" ") || "Belgenin gizlilik ve kişisel veri bulgularını kontrol edin.", tone: "danger" }]
      : []),
    ...(analysis.extraction.used_ocr
      ? [{ title: "OCR metni doğrulanmalı", detail: "Belge görüntüden okundu; kritik alanları özgün belgeyle karşılaştırın.", tone: "warning" }]
      : []),
  ] : [];

  return (
    <Card className={`document-list-card ${selected ? "has-document-detail" : "is-table-view"}`} role="region" aria-label="Kayıtlı evraklar">
      <div className="table-toolbar document-list-toolbar">
        <Input
          fieldClassName="search-field"
          leadingIcon={<Search />}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Evrak adı, konu veya içerik ara…"
          aria-label="Evraklarda ara"
        />
        <Select value={type} onChange={(event) => setType(event.target.value)} aria-label="Dosya türüne göre filtrele">
          <option value="all">Tüm türler</option>
          {types.map((item) => <option key={item}>{item}</option>)}
        </Select>
        <Select value={date} onChange={(event) => setDate(event.target.value as DateFilter)} aria-label="Tarihe göre filtrele">
          <option value="all">Tüm tarihler</option>
          <option value="week">Son 7 gün</option>
          <option value="month">Son 30 gün</option>
        </Select>
        <Select value={status} onChange={(event) => setStatus(event.target.value as StatusFilter)} aria-label="Duruma göre filtrele">
          <option value="all">Tüm durumlar</option>
          <option value="analyzed">Analiz tamamlandı</option>
          <option value="pending">Analiz bekliyor</option>
          <option value="attention">İnceleme gerekli</option>
        </Select>
        <Button variant="secondary" leadingIcon={<ArrowDownAZ />} onClick={() => setAscending((value) => !value)}>
          {ascending ? "En eski" : "En yeni"}
        </Button>
      </div>
      {filtersActive && (
        <div className="document-active-filters" aria-label="Etkin filtreler">
          <span>Etkin filtreler</span>
          {query && <span className="document-filter-chip">Arama: {query}</span>}
          {type !== "all" && <span className="document-filter-chip">Tür: {type}</span>}
          {date !== "all" && <span className="document-filter-chip">{date === "week" ? "Son 7 gün" : "Son 30 gün"}</span>}
          {status !== "all" && <span className="document-filter-chip">Durum: {status === "pending" ? "Analiz bekliyor" : status === "attention" ? "İnceleme gerekli" : "Analiz tamamlandı"}</span>}
          <Button variant="ghost" size="sm" leadingIcon={<X />} onClick={resetFilters}>Filtreleri temizle</Button>
        </div>
      )}

      {loading && documents.length === 0 ? (
        <div className="table-loading"><Spinner label="Evraklar yükleniyor" />Evraklar yükleniyor…</div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="Evrak bulunamadı"
          description={query || type !== "all" || status !== "all" || date !== "all" ? "Arama veya filtre ölçütlerini değiştirin." : "Sağ üstteki Evrak yükle düğmesiyle ilk evrakınızı yükleyin."}
        />
      ) : selected ? (
        <div className="document-library-layout">
          <div className="document-master-column">
            <div className="document-result-count"><strong>{filtered.length} sonuç</strong></div>
            <ul className="document-master-list" aria-label="Evrak listesi">
              {visibleDocuments.map((item) => {
                const expanded = selected.storage_path === item.storage_path;
                const detailId = `document-detail-${item.storage_path.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
                return (
                  <li key={item.storage_path} className={expanded ? "is-selected" : undefined}>
                    <DocumentListItem
                      document={item}
                      detailId={detailId}
                      expanded={expanded}
                      onToggle={() => selectWithTab(item, "summary")}
                      onViewAnalysis={() => selectWithTab(item, "analysis")}
                      onAnalyze={onAnalyzeDocument ? () => void onAnalyzeDocument(item.storage_path).catch(() => undefined) : undefined}
                      analyzing={analyzingStoragePath === item.storage_path}
                      onDelete={onDeleteDocument ? () => setPendingDeletePath(item.storage_path) : undefined}
                    />
                  </li>
                );
              })}
            </ul>
          </div>

          <section id={`document-detail-${selected.storage_path.replace(/[^a-zA-Z0-9_-]/g, "-")}`} className="document-detail-pane" aria-label="Evrak ayrıntıları">
            <header className="document-detail-header">
              <span className="document-detail-file-icon" aria-hidden="true"><FileText /></span>
              <div><h2>{selected.file_name}</h2><p>{selected.document_type_label || selected.document_type || "Belge"} · {selected.file_name.split(".").pop()?.toLocaleUpperCase("tr-TR") || "DOSYA"} · {formatDate(selected.upload_time)}</p></div>
              {selectedStatus && <StatusBadge tone={selectedStatus.tone}>{selectedStatus.label}</StatusBadge>}
              {onClose && <IconButton variant="ghost" icon={<ArrowLeft />} aria-label="Liste görünümüne dön" title="Liste görünümüne dön" onClick={onClose} />}
            </header>

            <div className="document-detail-actions">
              {selected.analyzed === false && onAnalyzeDocument ? (
                <Button leadingIcon={<FileSearch />} loading={analyzingStoragePath === selected.storage_path} onClick={() => void onAnalyzeDocument(selected.storage_path).catch(() => undefined)}>Analiz et</Button>
              ) : selectedNeedsReview ? (
                <Button leadingIcon={<FileSearch />} onClick={() => setDetailTab("analysis")}>Analizi incele</Button>
              ) : (
                <Link className="button button-primary control-md" to="/drafts"><FilePenLine />Taslak hazırla</Link>
              )}
              <Link className="button button-secondary control-md" to="/chats"><MessageSquare />Sohbette aç</Link>
            </div>

            <Tabs<DetailTab>
              label="Evrak ayrıntısı bölümleri"
              active={detailTab}
              onChange={setDetailTab}
              items={[
                { id: "summary", label: "Özet" },
                { id: "analysis", label: "Analiz" },
                { id: "text", label: "Belge Metni" },
                { id: "details", label: "Ayrıntılar" },
              ]}
            />

            <div className="document-detail-scroll" role="tabpanel">
              {selected.analyzed === false ? (
                <div className="document-analysis-pending">
                  <span className="document-detail-pending-icon"><FileSearch /></span>
                  <div><strong>Bu evrak henüz analiz edilmedi</strong><p>Belge türü, özet ve ilgili alanları oluşturmak için analizi başlatın.</p></div>
                  {onAnalyzeDocument && <Button loading={analyzingStoragePath === selected.storage_path} onClick={() => void onAnalyzeDocument(selected.storage_path).catch(() => undefined)}>Analizi başlat</Button>}
                </div>
              ) : loading && !analysis ? (
                <div className="centered-state"><Spinner label="Analiz ayrıntıları yükleniyor" />Analiz ayrıntıları yükleniyor…</div>
              ) : detailTab === "summary" ? (
                <div className="document-reference-summary">
                  <div className="document-summary-overview">
                    <section><h3>Evrak Özeti</h3><p>{selected.summary || "Bu evrak için henüz bir özet bulunmuyor."}</p></section>
                    <aside aria-label="Evrak hızlı bilgileri">
                      <span><small>Tür</small><strong>{selected.document_type_label || selected.document_type || "Belge"}</strong></span>
                      <span><small>Durum</small><strong>{selectedStatus?.label || "—"}</strong></span>
                      <span><small>Sayfa</small><strong>{analysis?.extraction.page_count ?? "—"}</strong></span>
                    </aside>
                  </div>
                  {primaryFields.length > 0 && <section><h3>Temel bilgiler</h3><dl>{primaryFields.map((item) => <div key={item.key}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl></section>}
                  {analysis && <section className="document-detected-elements"><h3>Tespit edilen unsurlar</h3><div className="document-detected-counts"><span><strong>{detectedEntities.length}</strong> ad/kurum/yer</span><span><strong>{analysis.fields.ilgi?.length ?? 0}</strong> ilgi</span><span><strong>{analysis.fields.ekler?.length ?? 0}</strong> ek</span></div>{detectedEntities.length > 0 && <ul>{detectedEntities.map((entity) => <li key={entity}>{entity}</li>)}</ul>}</section>}
                </div>
              ) : detailTab === "details" ? (
                <dl className="document-reference-metadata">
                  <div><dt>Evrak adı</dt><dd>{selected.file_name}</dd></div>
                  <div><dt>Evrak türü</dt><dd>{selected.document_type_label || selected.document_type || "—"}</dd></div>
                  <div><dt>Yükleme tarihi</dt><dd>{formatDate(selected.upload_time)}</dd></div>
                  <div><dt>Durum</dt><dd>{selectedStatus?.label || "—"}</dd></div>
                  <div><dt>Sayfa sayısı</dt><dd>{analysis?.extraction.page_count ?? "—"}</dd></div>
                  <div><dt>Karakter sayısı</dt><dd>{analysis?.extraction.char_count?.toLocaleString("tr-TR") ?? "—"}</dd></div>
                  <div><dt>Metin çıkarma yöntemi</dt><dd>{analysis?.extraction.extractor ?? "—"}</dd></div>
                  <div><dt>OCR kullanıldı</dt><dd>{analysis?.extraction.used_ocr ? "Evet" : "Hayır"}</dd></div>
                </dl>
              ) : detailTab === "text" ? (
                <section className="document-reference-text">
                  <header><div><h3>Belge Metni</h3><p>Çıkarılan metin sayfa düzeni korunarak gösterilir.</p></div><div>{onSaveText && !editingText && <Button variant="secondary" size="sm" leadingIcon={<Pencil />} onClick={() => { setTextDraft(documentText?.pages ?? []); setEditingText(true); setTextError(null); }}>Düzenle</Button>}{onReextract && !editingText && <Button variant="ghost" size="sm" leadingIcon={<RefreshCw />} loading={reextracting} onClick={() => void onReextract(selected.storage_path).catch(() => setTextError("Belge metni yeniden çıkarılamadı."))}>Yeniden çıkar</Button>}</div></header>
                  {textError && <p className="document-text-error">{textError}</p>}
                  {!documentText?.pages.length ? <p className="detail-empty">Belge metni henüz yüklenmedi veya bulunmuyor.</p> : editingText ? (
                    <div className="document-text-editor">{textDraft.map((pageText, index) => <Textarea key={index} label={`Sayfa ${index + 1}/${textDraft.length}`} rows={12} value={pageText} onChange={(event) => setTextDraft((current) => current.map((value, pageIndex) => pageIndex === index ? event.target.value : value))} />)}<div><Button variant="ghost" disabled={savingText} onClick={() => setEditingText(false)}>Vazgeç</Button><Button loading={savingText} onClick={() => void onSaveText?.(selected.storage_path, textDraft).then(() => setEditingText(false)).catch(() => setTextError("Belge metni kaydedilemedi."))}>Kaydet</Button></div></div>
                  ) : <div className="document-text-pages">{documentText.pages.map((pageText, index) => <article key={index} className="document-text-page-block"><h4>Sayfa {index + 1}/{documentText.pages.length}</h4><p className="document-text-page">{pageText}</p></article>)}</div>}
                </section>
              ) : (
                <div className="document-decision-analysis">
                  <section className={`document-analysis-verdict ${analysisIssues.length ? "needs-review" : "is-ready"}`}><span>{analysisIssues.length ? <AlertTriangle /> : <CheckCircle2 />}</span><div><h3>{analysisIssues.length ? `${analysisIssues.length} konu incelenmeli` : "Belge karar sürecine hazır"}</h3><p>{analysisIssues.length ? "Taslak veya yönlendirme öncesinde aşağıdaki bulguları doğrulayın." : "Zorunlu alanlar ve güvenlik kontrolleri tamamlandı."}</p></div></section>
                  {analysisIssues.length > 0 && <section><h3>İnceleme başlıkları</h3><ol className="document-issue-list">{analysisIssues.map((issue, index) => <li key={`${issue.title}-${index}`} className={`is-${issue.tone}`}><span>{index + 1}</span><div><strong>{issue.title}</strong><p>{issue.detail}</p></div></li>)}</ol></section>}
                  {analysis && <section><h3>Mevzuat ve dayanaklar</h3>{analysis.mevzuat_references.length ? <ul className="document-reference-list">{analysis.mevzuat_references.map((item, index) => <li key={`${item.mevzuat}-${index}`}><strong>{item.mevzuat}</strong><p>{item.aciklama}</p></li>)}</ul> : <p className="detail-empty">Ek bir mevzuat önerisi bulunmadı.</p>}</section>}
                  <DocumentAnalysisPanel variant="compact" analysis={analysis} saving={updatingFields} onSave={onUpdateFields && analysis ? (fields) => onUpdateFields(analysis.storage_path, fields) : undefined} generatingDetailedSummary={generatingDetailedSummary} onGenerateDetailedSummary={onGenerateDetailedSummary && analysis ? () => onGenerateDetailedSummary(analysis.storage_path) : undefined} documentGraph={documentGraph} loadingDocumentGraph={loadingDocumentGraph} />
                </div>
              )}
            </div>
          </section>
        </div>
      ) : (
        <>
          <div className="document-result-count"><strong>{filtered.length} sonuç</strong></div>
          <div className="document-reference-table" role="table" aria-label="Evrak kütüphanesi">
            <div className="document-reference-table-header" role="row">
              {['Evrak adı', 'Tür', 'Tarih', 'Durum', 'İşlemler'].map((label) => <span key={label} role="columnheader">{label}</span>)}
            </div>
            <div role="rowgroup">
              {visibleDocuments.map((document) => {
                const itemStatus = documentStatus(document);
                return (
                  <div className="document-reference-table-row" role="row" key={document.storage_path}>
                    <button type="button" className="document-reference-name" role="cell" onClick={() => selectWithTab(document, "summary")}><span><FileText /></span><span><strong>{document.file_name}</strong><small>{document.summary || "Özet bulunmuyor."}</small></span></button>
                    <span role="cell">{document.document_type_label || document.document_type || "—"}</span>
                    <time role="cell" dateTime={document.upload_time}>{formatDate(document.upload_time)}</time>
                    <span role="cell"><StatusBadge tone={itemStatus.tone}>{itemStatus.label}</StatusBadge></span>
                    <span className="document-reference-row-actions" role="cell"><DocumentActionsMenu document={document} onSelect={() => selectWithTab(document, "summary")} onViewAnalysis={() => selectWithTab(document, "analysis")} onAnalyze={onAnalyzeDocument ? () => void onAnalyzeDocument(document.storage_path).catch(() => undefined) : undefined} analyzing={analyzingStoragePath === document.storage_path} onDelete={onDeleteDocument ? () => setPendingDeletePath(document.storage_path) : undefined} /></span>
                  </div>
                );
              })}
            </div>
          </div>
          <footer className="document-pagination">
            <span>{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)} / {filtered.length}</span>
            <div><IconButton variant="ghost" icon={<ChevronLeft />} aria-label="Önceki sayfa" disabled={page === 1} onClick={() => setPage((value) => Math.max(1, value - 1))} /><span>{page} / {totalPages}</span><IconButton variant="ghost" icon={<ChevronRight />} aria-label="Sonraki sayfa" disabled={page === totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))} /></div>
          </footer>
        </>
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
