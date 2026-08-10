import {
  ChevronDown,
  ChevronUp,
  Copy,
  FilePenLine,
  FileText,
  History,
  Plus,
  X,
} from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { Button } from "../components/Button";
import { FormActions, Grid } from "../components/LayoutPrimitives";
import { EmptyState } from "../components/EmptyState";
import { Select, Textarea } from "../components/FormControls";
import { PageHeader } from "../components/PageHeader";
import { SectionHeader } from "../components/SectionHeader";
import { StatusBadge } from "../components/StatusBadge";
import { Card, Spinner } from "../components/Surface";
import { useDraftCreation } from "../hooks/useDraftCreation";
import { useDrafts } from "../hooks/useDrafts";
import type { PersistedDraft } from "../types/drafts";
import type { DocumentAnalysis, DocumentMetadata, ReasoningLevel } from "../types/documents";
import { DraftTable } from "../features/drafts/DraftTable";

const VERSION_PREVIEW_LIMIT = 420;

function ExpandableDraftContent({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false);
  const contentId = useId();
  const hasMore = content.length > VERSION_PREVIEW_LIMIT;
  const visibleContent = hasMore && !expanded
    ? `${content.slice(0, VERSION_PREVIEW_LIMIT).trimEnd()}…`
    : content;

  return (
    <div className="draft-version-content">
      <pre id={contentId}>{visibleContent}</pre>
      {hasMore && (
        <Button
          variant="ghost"
          size="sm"
          fullWidth
          className="draft-content-toggle"
          aria-controls={contentId}
          aria-expanded={expanded}
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? (
            <>Daha az göster<ChevronUp /></>
          ) : (
            <>Tümünü gör<ChevronDown /></>
          )}
        </Button>
      )}
    </div>
  );
}

function sortVersionsNewestFirst(versions: PersistedDraft[]) {
  return [...versions].sort((left, right) => right.version - left.version);
}

export function DraftsPage({
  documents,
  selected,
  analysis,
  activeDraftId,
  onSelect,
  onOpenDraft,
  onCloseDraft,
}: {
  documents: DocumentMetadata[];
  selected: DocumentMetadata | null;
  analysis: DocumentAnalysis | null;
  activeDraftId?: string;
  onSelect: (document: DocumentMetadata) => void;
  onOpenDraft: (draftId: string) => void;
  onCloseDraft?: () => void;
}) {
  const drafts = useDrafts(activeDraftId);
  const creation = useDraftCreation();
  const [formOpen, setFormOpen] = useState(false);
  const [type, setType] = useState("");
  const [level, setLevel] = useState<ReasoningLevel>("balanced");
  const [instructions, setInstructions] = useState("");
  const [copiedDraftId, setCopiedDraftId] = useState<string | null>(null);

  const create = async () => {
    if (!selected || !analysis) return;
    const result = await creation.create({
      storage_path: selected.storage_path,
      classification: {
        document_type: analysis.document_type,
        document_type_label: analysis.document_type_label,
        summary: analysis.summary,
        fields: analysis.fields,
        missing_fields: analysis.missing_fields,
        mevzuat_references: analysis.mevzuat_references,
      },
      instructions,
      correspondence_type: type || null,
      reasoning_level: level,
    });
    if (result.draft_id) {
      setFormOpen(false);
      onOpenDraft(result.draft_id);
    }
  };

  const copy = async (draft: PersistedDraft) => {
    await navigator.clipboard.writeText(draft.content);
    setCopiedDraftId(draft.id);
    window.setTimeout(() => setCopiedDraftId(null), 2000);
  };

  const documentName = (documentId: string | null) => {
    if (!documentId) return "Kaynak yok";
    const document = documents.find((item) => item.storage_path === documentId);
    return document?.file_name ?? documentId.split(/[\\/]/).pop() ?? documentId;
  };

  const draftTitle = (draft: PersistedDraft) => {
    const knownType = creation.correspondenceTypes.find(
      (item) => item.value === draft.correspondence_type,
    );
    if (knownType) return knownType.label;
    if (!draft.correspondence_type) return "Resmî taslak";
    return draft.correspondence_type.replace(/_/g, " ");
  };

  const expandedVersions = drafts.versions.length > 0
    ? sortVersionsNewestFirst(drafts.versions)
    : drafts.activeDraft
      ? [drafts.activeDraft]
      : [];

  return (
    <div className="page page-scroll drafts-page">
      <PageHeader
        title="Taslaklar"
        description="Oluşturulan taslakları, kaynak evraklarını ve sürüm geçmişlerini inceleyin."
        primaryAction={(
          <Button
            variant={formOpen ? "outline" : "primary"}
            aria-controls="draft-create-panel"
            aria-expanded={formOpen}
            onClick={() => setFormOpen((current) => !current)}
            leadingIcon={formOpen ? <X /> : <Plus />}
          >
            {formOpen ? "Formu kapat" : "Yeni taslak"}
          </Button>
        )}
      />

      <ApiErrorNotice
        error={drafts.errorObject ?? creation.errorObject ?? drafts.error ?? creation.error}
      />

      {formOpen && (
        <Card id="draft-create-panel" className="draft-create-panel" padding="prominent" role="region" aria-label="Yeni taslak oluştur">
          <SectionHeader title="Yeni taslak oluştur" description="Bir kaynak evrak seçin; diğer ayarları yalnızca gerektiğinde değiştirin." />
          <Grid className="draft-create-grid" min="15rem">
            <Select
                label="Kaynak evrak"
                fieldClassName="draft-source-field"
                value={selected?.storage_path ?? ""}
                onChange={(event) => {
                  const item = documents.find(
                    (document) => document.storage_path === event.target.value,
                  );
                  if (item) onSelect(item);
                }}
              >
                <option value="">Evrak seçin</option>
                {documents.map((document) => (
                  <option key={document.storage_path} value={document.storage_path}>
                    {document.file_name}
                  </option>
                ))}
              </Select>
            <Select
                label="Yazışma türü"
                value={type}
                disabled={creation.typesLoading}
                onChange={(event) => setType(event.target.value)}
              >
                <option value="">Otomatik belirle</option>
                {creation.correspondenceTypes.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </Select>
            <Select
                label="Düşünme seviyesi"
                value={level}
                onChange={(event) => setLevel(event.target.value as ReasoningLevel)}
              >
                <option value="fast">Hızlı</option>
                <option value="balanced">Dengeli</option>
                <option value="deep">Derin</option>
              </Select>
            <Textarea
                label="Ek talimat"
                counter={`${instructions.length}/4000`}
                fieldClassName="draft-instructions-field"
                value={instructions}
                maxLength={4000}
                rows={2}
                placeholder="İsteğe bağlı kısa bir talimat ekleyin."
                onChange={(event) => setInstructions(event.target.value)}
              />
            <FormActions className="draft-create-submit">
              <Button
                loading={creation.creating}
                disabled={!selected || !analysis}
                onClick={() => void create()}
              >Taslak oluştur</Button>
            </FormActions>
          </Grid>
        </Card>
      )}

      <Card className="draft-list-section" padding="default">
        <SectionHeader title="Oluşturulan taslaklar" description={`${drafts.total} kalıcı taslak`} action={drafts.refreshing ? <small>Yenileniyor…</small> : undefined} />

        {drafts.loading ? (
          <div className="table-loading"><Spinner label="Taslaklar yükleniyor" />Taslaklar yükleniyor…</div>
        ) : drafts.drafts.length === 0 ? (
          <EmptyState
            icon={FilePenLine}
            title="Henüz taslak oluşturulmadı"
            description="Sağ üstteki Yeni taslak düğmesiyle ilk taslağınızı oluşturabilirsiniz."
          />
        ) : (
          <DraftTable
            drafts={drafts.drafts}
            activeDraftId={activeDraftId}
            titleFor={draftTitle}
            sourceFor={(draft) => documentName(draft.document_id)}
            onToggle={(draft, expanded) => {
              if (expanded) onCloseDraft?.();
              else onOpenDraft(draft.id);
            }}
            renderDetail={(_draft, detailId) => (
                    <div id={detailId} className="draft-table-detail" role="row">
                      {drafts.detailLoading ? (
                        <div className="centered-state"><Spinner label="Taslak sürümleri yükleniyor" />Taslak sürümleri yükleniyor…</div>
                      ) : drafts.activeDraft ? (
                        <>
                          <div className="draft-detail-toolbar">
                            <div className="draft-metrics">
                              <span>
                                <small>Güven skoru</small>
                                <strong>
                                  {typeof drafts.activeDraft.confidence_score === "number"
                                    ? `%${Math.round(drafts.activeDraft.confidence_score)}`
                                    : "—"}
                                </strong>
                              </span>
                              <span><small>Sürüm</small><strong>{drafts.activeDraft.version}</strong></span>
                              <span>
                                <small>Deneme</small>
                                <strong>{drafts.activeDraft.attempts ?? "—"}</strong>
                              </span>
                            </div>
                            <StatusBadge
                              tone={drafts.activeDraft.requires_human_approval ? "warning" : "success"}
                            >
                              {drafts.activeDraft.requires_human_approval ? "Onay gerekli" : "Hazır"}
                            </StatusBadge>
                          </div>

                          <div className="draft-detail-actions">
                            {drafts.activeDraft.document_id && (
                              <Link
                                className="button button-quiet"
                                to={`/documents/${encodeURIComponent(drafts.activeDraft.document_id)}`}
                              >
                                <FileText size={15} /> Kaynak evraka git
                              </Link>
                            )}
                            <Button
                              variant="secondary"
                              leadingIcon={<Copy />}
                              onClick={() => void copy(drafts.activeDraft!)}
                            >
                              {copiedDraftId === drafts.activeDraft.id ? "Kopyalandı" : "Son sürümü kopyala"}
                            </Button>
                          </div>

                          <div className="draft-versions-heading">
                            <History size={17} />
                            <h3>Sürüm geçmişi</h3>
                            <span>{expandedVersions.length}</span>
                          </div>
                          <ol className="draft-version-list">
                            {expandedVersions.map((version) => (
                              <li key={version.id}>
                                <header>
                                  <strong>Sürüm {version.version}</strong>
                                  {version.id === drafts.activeDraft?.id && <span>Güncel</span>}
                                  <time dateTime={version.created_at}>
                                    {new Date(version.created_at).toLocaleString("tr-TR")}
                                  </time>
                                </header>
                                <ExpandableDraftContent content={version.content} />
                              </li>
                            ))}
                          </ol>
                        </>
                      ) : (
                        <p className="detail-empty">Taslak ayrıntısı yüklenemedi.</p>
                      )}
                    </div>
            )}
          />
        )}
      </Card>
    </div>
  );
}
