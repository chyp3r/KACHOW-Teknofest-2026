import { Copy, FilePenLine } from "lucide-react";
import { useEffect, useState } from "react";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { DraftHistory } from "../features/drafts/DraftHistory";
import type { DraftHistoryEntry } from "../hooks/useDraftHistory";
import { documentService } from "../services/documentService";
import type {
  CorrespondenceType,
  DocumentAnalysis,
  DocumentMetadata,
  DraftResult,
  ReasoningLevel,
} from "../types/documents";

const FALLBACK_TYPES: CorrespondenceType[] = [
  { value: "cover_letter", label: "Üst yazı" },
  { value: "response_letter", label: "Cevap yazısı" },
  { value: "information_notice", label: "Bilgilendirme metni" },
  { value: "other_official", label: "Diğer resmî yazışma" },
];

export function DraftsPage({
  documents,
  selected,
  analysis,
  draft,
  history,
  onSelect,
  onDraftCreated,
  onHistorySelect,
}: {
  documents: DocumentMetadata[];
  selected: DocumentMetadata | null;
  analysis: DocumentAnalysis | null;
  draft: DraftResult | null;
  history: DraftHistoryEntry[];
  onSelect: (document: DocumentMetadata) => void;
  onDraftCreated: (draft: DraftResult) => void;
  onHistorySelect: (entry: DraftHistoryEntry) => void;
}) {
  const [types, setTypes] = useState(FALLBACK_TYPES);
  const [type, setType] = useState("");
  const [level, setLevel] = useState<ReasoningLevel>("balanced");
  const [instructions, setInstructions] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    documentService
      .correspondenceTypes()
      .then((items) => items.length && setTypes(items))
      .catch(() => undefined);
  }, []);
  const create = async () => {
    if (!selected || !analysis) return;
    setSubmitting(true);
    setError(null);
    try {
      onDraftCreated(
        await documentService.createDraft({
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
        }),
      );
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Taslak oluşturulamadı.",
      );
    } finally {
      setSubmitting(false);
    }
  };
  const copy = async () => {
    if (!draft) return;
    await navigator.clipboard.writeText(draft.draft);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="page page-scroll">
      <PageHeader
        title="Taslaklar"
        description="Seçili evrakın analizinden resmî yazı taslağı oluşturun ve sonucu inceleyin."
      />
      <DraftHistory
        entries={history}
        activeDraft={draft}
        onSelect={onHistorySelect}
      />
      <div className="drafts-layout">
        <section className="surface draft-form">
          <div className="section-heading">
            <div>
              <h2>Yeni taslak oluştur</h2>
              <p>Taslak üretimi mevcut evrak analizi üzerinden çalışır.</p>
            </div>
          </div>
          <div className="form-stack">
            <label>
              Kaynak evrak
              <select
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
                  <option
                    key={document.storage_path}
                    value={document.storage_path}
                  >
                    {document.file_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Yazışma türü
              <select
                value={type}
                onChange={(event) => setType(event.target.value)}
              >
                <option value="">Otomatik belirle</option>
                {types.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Düşünme seviyesi
              <select
                value={level}
                onChange={(event) =>
                  setLevel(event.target.value as ReasoningLevel)
                }
              >
                <option value="fast">Hızlı</option>
                <option value="balanced">Dengeli</option>
                <option value="deep">Derin</option>
              </select>
            </label>
            <label>
              Ek talimat
              <textarea
                value={instructions}
                maxLength={4000}
                onChange={(event) => setInstructions(event.target.value)}
                placeholder="Örnek: Talebi olumlu karşıla, ek süre 15 gün olsun."
              />
            </label>
            {error && <p className="feedback error">{error}</p>}
            <button
              className="button button-primary"
              disabled={!selected || !analysis || submitting}
              onClick={() => void create()}
            >
              {submitting ? "Taslak oluşturuluyor…" : "Taslak oluştur"}
            </button>
          </div>
        </section>
        <section className="surface draft-result">
          {draft ? (
            <>
              <div className="section-heading">
                <div>
                  <h2>Oluşturulan taslak</h2>
                  <p>{draft.destination || "Hedef birim henüz belirlenmedi"}</p>
                </div>
                <StatusBadge
                  tone={draft.requires_human_approval ? "warning" : "success"}
                >
                  {draft.requires_human_approval ? "Onay gerekli" : "Hazır"}
                </StatusBadge>
              </div>
              <div className="draft-metrics">
                <span>
                  <small>Güven skoru</small>
                  <strong>%{Math.round(draft.confidence_score)}</strong>
                </span>
                <span>
                  <small>Deneme</small>
                  <strong>{draft.attempts}</strong>
                </span>
              </div>
              {draft.missing_information.length > 0 && (
                <div className="notice warning">
                  Eksik bilgiler:{" "}
                  {draft.missing_information
                    .map((item) => item.label)
                    .join(", ")}
                </div>
              )}
              <pre className="draft-document">{draft.draft}</pre>
              <button
                className="button button-secondary"
                onClick={() => void copy()}
              >
                <Copy size={16} />
                {copied ? "Kopyalandı" : "Metni kopyala"}
              </button>
            </>
          ) : (
            <EmptyState
              icon={FilePenLine}
              title="Henüz taslak oluşturulmadı"
              description="Bir kaynak evrak seçip formu tamamlayın veya geçmişten bir taslak açın."
            />
          )}
        </section>
      </div>
    </div>
  );
}
