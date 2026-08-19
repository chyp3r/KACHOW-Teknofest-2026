import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  FilePenLine,
  FileText,
  History,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Send,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { Button } from "../components/Button";
import { ConfirmationDialog } from "../components/ConfirmationDialog";
import { EmptyState } from "../components/EmptyState";
import { FormActions, Grid } from "../components/LayoutPrimitives";
import { Input, Select, Textarea } from "../components/FormControls";
import { PageHeader } from "../components/PageHeader";
import { SectionHeader } from "../components/SectionHeader";
import { StatusBadge } from "../components/StatusBadge";
import { Card, Spinner } from "../components/Surface";
import { Tabs } from "../components/Tabs";
import { DraftDocumentPreview } from "../features/drafts/DraftDocumentPreview";
import { DraftRoutingPanel } from "../features/drafts/DraftRoutingPanel";
import { DraftSendDialog } from "../features/drafts/DraftSendDialog";
import { UnitPicker } from "../features/drafts/UnitPicker";
import { useDraftCreation } from "../hooks/useDraftCreation";
import { useDrafts } from "../hooks/useDrafts";
import type { DraftShare, PersistedDraft } from "../types/drafts";
import type { DocumentAnalysis, DocumentMetadata, ReasoningLevel } from "../types/documents";
import { correspondenceTypeLabel, documentName, draftSubject } from "./draftTitle";

type WorkspaceTab = "mine" | "inbox" | "outbox";
type DetailTab = "draft" | "control" | "routing" | "versions" | "details";

function formatDate(value: string, withTime = false) {
  return new Intl.DateTimeFormat("tr-TR", withTime
    ? { dateStyle: "medium", timeStyle: "short" }
    : { dateStyle: "medium" }).format(new Date(value));
}

function draftState(draft: PersistedDraft) {
  const issues = Math.max(draft.missing_information?.length ?? 0, draft.requires_human_approval ? 1 : 0);
  if (draft.status?.toLocaleLowerCase("tr-TR") === "sent") return { label: "Gönderildi", tone: "info" as const, issues: 0 };
  if (issues > 0) return { label: "İnceleme gerekli", tone: "warning" as const, issues };
  if ((draft.confidence_score ?? 0) >= 80 || draft.status?.toLocaleLowerCase("tr-TR") === "ready") return { label: "Hazır", tone: "success" as const, issues: 0 };
  return { label: "Taslak", tone: "pending" as const, issues: 0 };
}

function shareState(status: string) {
  const labels: Record<string, string> = {
    sent: "Gönderildi",
    read: "Okundu",
    accepted: "Kabul edildi",
    rejected: "Reddedildi",
    withdrawn: "Geri çekildi",
  };
  return labels[status] ?? status;
}

function shareTitle(share: DraftShare) {
  return draftSubject({ content: share.content ?? "" })
    ?? share.correspondence_type?.replace(/_/g, " ")
    ?? "Paylaşılan taslak";
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
  const drafts = useDrafts(activeDraftId, true);
  const creation = useDraftCreation();
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("mine");
  const [detailTab, setDetailTab] = useState<DetailTab>("draft");
  const [formOpen, setFormOpen] = useState(false);
  const [type, setType] = useState("");
  const [level, setLevel] = useState<ReasoningLevel>("balanced");
  const [instructions, setInstructions] = useState("");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [destinationFilter, setDestinationFilter] = useState("all");
  const [ascending, setAscending] = useState(false);
  const [selectedShareId, setSelectedShareId] = useState<string | null>(null);
  const [previewVersion, setPreviewVersion] = useState<PersistedDraft | null>(null);
  const [sendOpen, setSendOpen] = useState(false);
  const [copiedDraftId, setCopiedDraftId] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [pendingRevokeShareId, setPendingRevokeShareId] = useState<string | null>(null);

  useEffect(() => {
    setPreviewVersion(null);
  }, [activeDraftId]);

  const draftTypeFor = (draft: PersistedDraft) => correspondenceTypeLabel(draft, creation.correspondenceTypes);
  const draftSubjectFor = (draft: PersistedDraft) => draftSubject(draft) ?? documentName(draft.document_id, documents);
  const destinations = [...new Set(drafts.drafts.map((draft) => draft.destination).filter(Boolean) as string[])];
  const filteredDrafts = drafts.drafts
    .filter((draft) => {
      const state = draftState(draft);
      const copy = `${draftSubjectFor(draft)} ${draftTypeFor(draft)} ${draft.destination ?? ""}`.toLocaleLowerCase("tr-TR");
      return copy.includes(query.toLocaleLowerCase("tr-TR"))
        && (statusFilter === "all" || (statusFilter === "review" ? state.issues > 0 : state.label.toLocaleLowerCase("tr-TR") === statusFilter))
        && (destinationFilter === "all" || draft.destination === destinationFilter);
    })
    .sort((left, right) => (new Date(left.updated_at).getTime() - new Date(right.updated_at).getTime()) * (ascending ? 1 : -1));
  const shares = (workspaceTab === "inbox" ? drafts.inbox : drafts.outbox) ?? [];
  const filteredShares = shares.filter((share) => `${shareTitle(share)} ${share.destination ?? ""} ${shareState(share.status)}`.toLocaleLowerCase("tr-TR").includes(query.toLocaleLowerCase("tr-TR")));
  const selectedShare = filteredShares.find((share) => share.id === selectedShareId) ?? null;
  const activeDraft = previewVersion ?? drafts.activeDraft;
  const activeState = activeDraft ? draftState(activeDraft) : null;
  const sourceDocument = activeDraft?.document_id ? documents.find((document) => document.storage_path === activeDraft.document_id) : null;
  const sortedVersions = [...drafts.versions].sort((left, right) => right.version - left.version);

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

  const confirmDelete = async () => {
    if (!pendingDeleteId) return;
    const deletingActive = pendingDeleteId === activeDraftId;
    await drafts.deleteDraft(pendingDeleteId);
    setPendingDeleteId(null);
    if (deletingActive) onCloseDraft?.();
  };

  const openDraft = (draft: PersistedDraft, tab: DetailTab = "draft") => {
    setPreviewVersion(null);
    setDetailTab(tab);
    onOpenDraft(draft.id);
  };

  return (
    <div className="page page-scroll drafts-page">
      <PageHeader
        title="Taslaklar"
        description="Taslaklarınızı inceleyin, revize edin ve ilgili birimlere gönderin."
        primaryAction={<Button variant={formOpen ? "outline" : "primary"} aria-controls="draft-create-panel" aria-expanded={formOpen} onClick={() => setFormOpen((current) => !current)} leadingIcon={formOpen ? <X /> : <Plus />}>{formOpen ? "Formu kapat" : "Yeni taslak"}</Button>}
      />
      <ApiErrorNotice error={drafts.errorObject ?? creation.errorObject ?? drafts.error ?? creation.error} />

      {formOpen && (
        <Card id="draft-create-panel" className="draft-create-panel" padding="prominent" role="region" aria-label="Yeni taslak oluştur">
          <SectionHeader title="Yazışma bilgileri" description="Taslağın yönünü belirlemek için mevcut bilgileri gözden geçirin." />
          <div className="draft-brief-layout">
            <Grid className="draft-create-grid" min="15rem">
              <Select label="Kaynak evrak" fieldClassName="draft-source-field" value={selected?.storage_path ?? ""} onChange={(event) => { const item = documents.find((document) => document.storage_path === event.target.value); if (item) onSelect(item); }}><option value="">Evrak seçin</option>{documents.map((document) => <option key={document.storage_path} value={document.storage_path}>{document.file_name}</option>)}</Select>
              <Select label="Yazışma türü" value={type} disabled={creation.typesLoading} onChange={(event) => setType(event.target.value)}><option value="">Otomatik belirle</option>{creation.correspondenceTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</Select>
              <Select label="Çalışma modu" value={level} onChange={(event) => setLevel(event.target.value as ReasoningLevel)}><option value="fast">Hızlı</option><option value="balanced">Dengeli</option><option value="deep">Derinlemesine</option></Select>
              <Textarea label="Ek talimat" counter={`${instructions.length}/4000`} fieldClassName="draft-instructions-field" value={instructions} maxLength={4000} rows={2} placeholder="İsteğe bağlı kısa bir talimat ekleyin." onChange={(event) => setInstructions(event.target.value)} />
              <FormActions className="draft-create-submit"><Button loading={creation.creating} disabled={!selected || !analysis} onClick={() => void create()}>Taslak oluştur</Button></FormActions>
            </Grid>
            <aside className="draft-brief-summary" aria-label="Seçilen yazışma bilgileri"><header><span><FilePenLine /></span><div><h3>Seçtiğiniz bilgiler</h3><p>Taslak bu bilgilerle hazırlanacak.</p></div></header><dl><div><dt><CheckCircle2 />Kaynak evrak</dt><dd>{selected?.file_name ?? "Henüz seçilmedi"}</dd></div><div><dt><CheckCircle2 />Yazışma türü</dt><dd>{creation.correspondenceTypes.find((item) => item.value === type)?.label ?? "Otomatik belirlenecek"}</dd></div><div><dt><CheckCircle2 />Çalışma modu</dt><dd>{level === "fast" ? "Hızlı" : level === "deep" ? "Derinlemesine" : "Dengeli"}</dd></div></dl></aside>
          </div>
        </Card>
      )}

      <div className="draft-workspace-tabs" role="tablist" aria-label="Taslak çalışma alanları">
        <button type="button" role="tab" aria-selected={workspaceTab === "mine"} onClick={() => { setWorkspaceTab("mine"); setSelectedShareId(null); }}>Taslaklarım <span>{drafts.total}</span></button>
        <button type="button" role="tab" aria-selected={workspaceTab === "inbox"} onClick={() => { setWorkspaceTab("inbox"); setSelectedShareId(null); }}>Gelenler <span>{drafts.inboxTotal}</span></button>
        <button type="button" role="tab" aria-selected={workspaceTab === "outbox"} onClick={() => { setWorkspaceTab("outbox"); setSelectedShareId(null); }}>Gönderilenler <span>{drafts.outboxTotal}</span></button>
      </div>

      <Card className="draft-workspace" padding="compact">
        <div className="draft-workspace-toolbar">
          <Input leadingIcon={<Search />} aria-label="Taslaklarda ara" placeholder="Taslak ara…" value={query} onChange={(event) => setQuery(event.target.value)} />
          {workspaceTab === "mine" && <Select aria-label="Taslak durumuna göre filtrele" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">Tüm durumlar</option><option value="review">İnceleme gerekli</option><option value="hazır">Hazır</option><option value="taslak">Taslak</option></Select>}
          {workspaceTab === "mine" && <Select aria-label="Hedef birime göre filtrele" value={destinationFilter} onChange={(event) => setDestinationFilter(event.target.value)}><option value="all">Tüm birimler</option>{destinations.map((destination) => <option key={destination}>{destination}</option>)}</Select>}
          <Button variant="secondary" onClick={() => setAscending((current) => !current)}>{ascending ? "En eski" : "En yeni"}</Button>
        </div>

        {drafts.loading ? <div className="table-loading"><Spinner label="Taslaklar yükleniyor" />Taslaklar yükleniyor…</div> : workspaceTab === "mine" ? (
          filteredDrafts.length === 0 ? <EmptyState icon={FilePenLine} title="Taslak bulunamadı" description="Filtreleri değiştirin veya yeni bir taslak oluşturun." /> : (
            <div className="draft-master-detail">
              <aside className="draft-master" aria-label="Taslaklarım"><header><strong>Taslaklarım</strong><span>{filteredDrafts.length} taslak</span></header><ul>{filteredDrafts.map((draft) => { const state = draftState(draft); return <li key={draft.id} className={draft.id === activeDraftId ? "is-selected" : undefined}><button type="button" aria-current={draft.id === activeDraftId ? "true" : undefined} onClick={() => openDraft(draft)}><span className="draft-list-icon"><FilePenLine /></span><span className="draft-list-copy"><strong>{draftSubjectFor(draft)}</strong><small>{draftTypeFor(draft)}</small><span>{draft.destination || "Hedef belirtilmedi"}</span><span><StatusBadge tone={state.tone}>{state.label}</StatusBadge><small>v{draft.version} · {formatDate(draft.updated_at)}</small></span></span></button></li>; })}</ul></aside>
              <main className="draft-detail-pane" aria-label="Taslak çalışma alanı">
                {!activeDraftId ? <EmptyState icon={FilePenLine} title="Bir taslak seçin" description="Taslağı incelemek ve sürümlerine erişmek için soldaki listeden seçim yapın." /> : drafts.detailLoading ? <div className="centered-state"><Spinner label="Taslak yükleniyor" />Taslak yükleniyor…</div> : activeDraft ? (
                  <>
                    <header className="draft-detail-header"><div><h2>{draftSubjectFor(activeDraft)}</h2><p>{draftTypeFor(activeDraft)} · v{activeDraft.version}{previewVersion ? " · Eski sürüm" : " · Güncel"}</p></div>{activeState && <StatusBadge tone={activeState.tone}>{activeState.label}</StatusBadge>}<div className="draft-header-actions"><Link className="button button-secondary control-md" to={`${activeDraft.session_id ? `/chats/${encodeURIComponent(activeDraft.session_id)}` : "/chats"}?draft=${encodeURIComponent(activeDraft.id)}&mode=revise`}><Pencil />Revize et</Link><Button leadingIcon={<Send />} onClick={() => setSendOpen(true)}>Gönder</Button><details className="draft-actions-menu"><summary aria-label="Taslak işlemleri"><MoreHorizontal /></summary><div role="menu"><Link role="menuitem" to={activeDraft.session_id ? `/chats/${encodeURIComponent(activeDraft.session_id)}` : "/chats"}><MessageSquare />Sohbette aç</Link>{activeDraft.document_id && <Link role="menuitem" to={`/documents/${encodeURIComponent(activeDraft.document_id)}`}><FileText />Kaynak evrakı aç</Link>}<button type="button" role="menuitem" onClick={() => void copy(activeDraft)}><Copy />{copiedDraftId === activeDraft.id ? "Kopyalandı" : "Kopyala"}</button><span aria-hidden="true" /><button type="button" role="menuitem" className="danger-text" onClick={() => setPendingDeleteId(activeDraft.id)}><Trash2 />Sil</button></div></details></div></header>
                    <Tabs<DetailTab> label="Taslak ayrıntısı bölümleri" active={detailTab} onChange={(nextTab) => { setDetailTab(nextTab); if (nextTab === "routing") setPreviewVersion(null); }} items={[{ id: "draft", label: "Taslak" }, { id: "control", label: "Kontrol" }, { id: "routing", label: "Yönlendirme" }, { id: "versions", label: `Sürümler (${sortedVersions.length || 1})` }, { id: "details", label: "Ayrıntılar" }]} />
                    <div className="draft-detail-scroll" role="tabpanel">
                      {detailTab === "draft" ? <div className="draft-review-layout"><DraftDocumentPreview content={activeDraft.content} /><aside className="draft-info-panel" aria-label="Taslak bilgileri"><h3>Taslak bilgileri</h3><dl><div><dt>Kontrol durumu</dt><dd>{activeState?.issues ? <><strong>İnceleme öneriliyor</strong><small>{activeState.issues} konu kontrol edilmeli</small></> : <strong>Gönderime hazır</strong>}</dd></div><div><dt>Hedef birim</dt><dd><strong>{activeDraft.destination || "Belirtilmedi"}</strong></dd></div><div><dt>Kaynak evrak</dt><dd>{activeDraft.document_id ? <Link to={`/documents/${encodeURIComponent(activeDraft.document_id)}`}>{sourceDocument?.file_name ?? documentName(activeDraft.document_id, documents)}</Link> : <span>Bağlı evrak yok</span>}</dd></div><div><dt>Son güncelleme</dt><dd>{formatDate(activeDraft.updated_at, true)}</dd></div><div><dt>Sürüm</dt><dd>v{activeDraft.version} · {previewVersion ? "Eski sürüm" : "Güncel"}</dd></div></dl></aside></div>
                      : detailTab === "control" ? <div className="draft-control-view"><section className={activeState?.issues ? "needs-review" : "is-ready"}><span>{activeState?.issues ? <AlertTriangle /> : <CheckCircle2 />}</span><div><h3>{activeState?.issues ? "İnceleme öneriliyor" : "Taslak gönderime hazır"}</h3><p>{activeState?.issues ? `${activeState.issues} konu gönderim öncesinde kontrol edilmeli.` : "Otomatik kontrollerde gönderimi engelleyen bir bulgu bulunmadı."}</p></div></section>{activeDraft.missing_information?.length ? <section><h3>Kontrol edilecek bilgiler</h3><ul>{activeDraft.missing_information.map((item) => <li key={item.key}><strong>{item.label}</strong><span>{item.why || "Bu alan doğrulanmalı."}</span></li>)}</ul></section> : null}<section className="draft-confidence-note"><h3>Güven göstergesi</h3><strong>{Math.round(activeDraft.confidence_score ?? 0)} / 100</strong><p>Bu gösterge tek başına doğruluk garantisi değildir; karar için kontrol başlıklarını esas alın.</p></section></div>
                      : detailTab === "routing" ? <DraftRoutingPanel draft={drafts.activeDraft ?? activeDraft} saving={drafts.updatingDestination} onSave={(destination) => void drafts.updateDestination((drafts.activeDraft ?? activeDraft).id, destination)} />
                      : detailTab === "versions" ? <div className="draft-versions-view"><header><History /><div><h3>Sürüm geçmişi</h3><p>Taslağın önceki kayıtlarını görüntüleyin.</p></div></header><ol>{(sortedVersions.length ? sortedVersions : [activeDraft]).map((version) => <li key={version.id}><div><strong>v{version.version}</strong>{version.id === drafts.activeDraft?.id && <StatusBadge tone="success">Güncel</StatusBadge>}<time dateTime={version.created_at}>{formatDate(version.created_at, true)}</time></div><Button variant="secondary" size="sm" onClick={() => { setPreviewVersion(version); setDetailTab("draft"); }}>Görüntüle</Button></li>)}</ol></div>
                      : <div className="draft-details-view"><dl><div><dt>Yazışma türü</dt><dd>{draftTypeFor(activeDraft)}</dd></div><div><dt>Kaynak evrak</dt><dd>{activeDraft.document_id ? <Link to={`/documents/${encodeURIComponent(activeDraft.document_id)}`}>{sourceDocument?.file_name ?? documentName(activeDraft.document_id, documents)}</Link> : "—"}</dd></div><div><dt>Hedef birim</dt><dd><strong>{activeDraft.destination || "Belirtilmedi"}</strong><UnitPicker currentDestination={drafts.activeDraft?.destination ?? activeDraft.destination} saving={drafts.updatingDestination} onSave={(destination) => void drafts.updateDestination(drafts.activeDraft?.id ?? activeDraft.id, destination)} /></dd></div><div><dt>Son güncelleme</dt><dd>{formatDate(activeDraft.updated_at, true)}</dd></div><div><dt>Sürüm</dt><dd>v{activeDraft.version}</dd></div><div><dt>Güven göstergesi</dt><dd>{Math.round(activeDraft.confidence_score ?? 0)} / 100</dd></div><div><dt>Oluşturma denemesi</dt><dd>{activeDraft.attempts ?? "—"}</dd></div></dl></div>}
                    </div>
                  </>
                ) : <EmptyState icon={FilePenLine} title="Taslak yüklenemedi" description="Listeyi yenileyip tekrar deneyin." />}
              </main>
            </div>
          )
        ) : filteredShares.length === 0 ? <EmptyState icon={Send} title={workspaceTab === "inbox" ? "Gelen taslak yok" : "Gönderilmiş taslak yok"} description={workspaceTab === "inbox" ? "Size gönderilen taslaklar burada görünür." : "Gönderdiğiniz taslaklar burada görünür."} /> : (
          <div className="draft-master-detail"><aside className="draft-master" aria-label={workspaceTab === "inbox" ? "Gelen taslaklar" : "Gönderilen taslaklar"}><header><strong>{workspaceTab === "inbox" ? "Gelenler" : "Gönderilenler"}</strong><span>{filteredShares.length} taslak</span></header><ul>{filteredShares.map((share) => <li key={share.id} className={share.id === selectedShareId ? "is-selected" : undefined}><button type="button" onClick={() => { setSelectedShareId(share.id); if (workspaceTab === "inbox" && share.status === "sent") void drafts.markShareRead(share.id); }}><span className="draft-list-icon"><Send /></span><span className="draft-list-copy"><strong>{share.status === "sent" && workspaceTab === "inbox" ? "● " : ""}{shareTitle(share)}</strong><small>{share.correspondence_type?.replace(/_/g, " ") || "Resmî taslak"}</small><span>{share.destination || "Hedef belirtilmedi"}</span><span><StatusBadge tone={share.status === "rejected" ? "danger" : share.status === "accepted" ? "success" : "info"}>{shareState(share.status)}</StatusBadge><small>{formatDate(share.created_at)}</small></span></span></button></li>)}</ul></aside><main className="draft-detail-pane" aria-label="Paylaşılan taslak ayrıntısı">{selectedShare ? <><header className="draft-detail-header"><div><h2>{shareTitle(selectedShare)}</h2><p>{selectedShare.correspondence_type?.replace(/_/g, " ") || "Resmî taslak"}</p></div><StatusBadge tone={selectedShare.status === "rejected" ? "danger" : selectedShare.status === "accepted" ? "success" : "info"}>{shareState(selectedShare.status)}</StatusBadge>{workspaceTab === "inbox" && ["sent", "read"].includes(selectedShare.status) && <div className="draft-header-actions"><Button variant="secondary" onClick={() => void drafts.respondToShare(selectedShare.id, "reject")}>Reddet</Button><Button loading={drafts.responding} onClick={() => void drafts.respondToShare(selectedShare.id, "accept")}>Kabul et</Button></div>}{workspaceTab === "outbox" && selectedShare.status === "sent" && <Button variant="destructive" loading={drafts.revokingShare} onClick={() => setPendingRevokeShareId(selectedShare.id)}>Gönderimi geri çek</Button>}</header><div className="draft-detail-scroll"><div className="draft-review-layout"><DraftDocumentPreview content={selectedShare.content || "Taslak içeriği bulunmuyor."} /><aside className="draft-info-panel"><h3>Paylaşım bilgileri</h3><dl><div><dt>Durum</dt><dd>{shareState(selectedShare.status)}</dd></div><div><dt>Hedef birim</dt><dd>{selectedShare.destination || "—"}</dd></div><div><dt>Gönderim tarihi</dt><dd>{formatDate(selectedShare.created_at, true)}</dd></div>{selectedShare.message && <div><dt>İletim notu</dt><dd>{selectedShare.message}</dd></div>}</dl></aside></div></div></> : <EmptyState icon={Send} title="Bir taslak seçin" description="Paylaşım ayrıntısını görmek için soldaki listeden seçim yapın." />}</main></div>
        )}
      </Card>

      {drafts.activeDraft && <DraftSendDialog open={sendOpen} title={draftSubjectFor(drafts.activeDraft)} draftId={drafts.activeDraft.id} destination={drafts.activeDraft.destination} sending={drafts.sending} onClose={() => setSendOpen(false)} onSend={(recipientIds, message) => drafts.sendDraft(drafts.activeDraft!.id, recipientIds, message)} />}
      <ConfirmationDialog open={pendingDeleteId !== null} title="Taslağı sil" description="Bu taslak ve tüm sürüm geçmişi kalıcı olarak listeden kaldırılacak. Bu işlem geri alınamaz." confirmLabel="Sil" busy={drafts.deleting} onConfirm={() => void confirmDelete()} onCancel={() => setPendingDeleteId(null)} />
      <ConfirmationDialog open={pendingRevokeShareId !== null} title="Gönderimi geri çek" description="Taslak paylaşımı alıcının gelen kutusundan geri çekilecek." confirmLabel="Geri çek" busy={drafts.revokingShare} onConfirm={() => pendingRevokeShareId && void drafts.revokeShare(pendingRevokeShareId).then(() => { setPendingRevokeShareId(null); setSelectedShareId(null); })} onCancel={() => setPendingRevokeShareId(null)} />
    </div>
  );
}
