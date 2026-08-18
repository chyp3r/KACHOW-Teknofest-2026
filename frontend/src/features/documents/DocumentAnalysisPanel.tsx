import { AlertTriangle, FileSearch, Pencil, ShieldAlert, X } from "lucide-react";
import { useEffect, useState } from "react";
import { StatusBadge } from "../../components/StatusBadge";
import { Alert, Card } from "../../components/Surface";
import { Button } from "../../components/Button";
import { Input, Textarea } from "../../components/FormControls";
import type { DocumentAnalysis, DocumentText, EvrakFields } from "../../types/documents";
import { SENSITIVITY_LABELS } from "../../types/security";

const MARK_KIND_LABELS: Record<"signature" | "stamp" | "handwriting", string> = {
  signature: "İmza",
  stamp: "Mühür/damga",
  handwriting: "El yazısı not",
};

const LABELS: Record<keyof EvrakFields, string> = {
  sayi: "Sayı",
  tarih: "Tarih",
  konu: "Konu",
  muhatap: "Muhatap",
  gonderen_kurum: "Gönderen kurum",
  ilgi: "İlgi",
  ekler: "Ekler",
  imza_sahibi: "İmza sahibi",
  imza_unvani: "İmza unvanı",
  gizlilik_derecesi: "Gizlilik derecesi",
  ivedilik: "İvedilik",
  basvuran_adi: "Başvuran adı",
  adres: "Adres",
  iletisim: "İletişim",
  entities: "Tespit edilen varlıklar",
};
//: Fields whose value is a list, rendered as one line per item in the edit
//: form's textarea instead of a single-line input.
const LIST_FIELDS = new Set<keyof EvrakFields>(["ilgi", "ekler", "entities"]);
const showValue = (value: unknown) =>
  Array.isArray(value)
    ? value.join(", ") || "—"
    : value === null || value === undefined || value === ""
      ? "—"
      : String(value);

function toFormValue(value: string | string[] | null | undefined): string {
  if (Array.isArray(value)) return value.join("\n");
  return value ?? "";
}

function fromFormValue(key: keyof EvrakFields, value: string): string | string[] {
  if (LIST_FIELDS.has(key)) {
    return value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  }
  return value;
}

export function DocumentAnalysisPanel({
  analysis,
  onSave,
  saving = false,
  onGenerateDetailedSummary,
  generatingDetailedSummary = false,
  documentText,
  onSaveText,
  savingText = false,
  onReextract,
  reextracting = false,
}: {
  analysis: DocumentAnalysis | null;
  // Undefined when the caller doesn't wire editing (e.g. no permission
  // hook available) -- the panel then stays read-only exactly as before.
  onSave?: (fields: EvrakFields) => Promise<void>;
  saving?: boolean;
  // Undefined the same way onSave is -- panel stays without the trigger
  // button, showing only the short summary above, if the caller doesn't
  // wire it. Takes no arguments: the caller already knows which document
  // (see onSave's own analogous shape one level up, in DocumentTable).
  onGenerateDetailedSummary?: () => Promise<void>;
  generatingDetailedSummary?: boolean;
  // Data-gated, like `guardrail`/`signature` below -- not capability-gated
  // like onGenerateDetailedSummary above, since there is genuinely nothing
  // to show without it (a separate, slower-loading query in useDocuments).
  documentText?: DocumentText | null;
  onSaveText?: (pages: string[]) => Promise<void>;
  savingText?: boolean;
  onReextract?: () => Promise<void>;
  reextracting?: boolean;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [detailedSummaryError, setDetailedSummaryError] = useState<string | null>(null);
  const [isEditingText, setIsEditingText] = useState(false);
  const [textDraft, setTextDraft] = useState<string[]>([]);
  const [textSaveError, setTextSaveError] = useState<string | null>(null);
  const [reextractError, setReextractError] = useState<string | null>(null);

  // A different document (or a fresh save) must never keep a stale edit
  // session open on top of it.
  useEffect(() => {
    setIsEditing(false);
    setSaveError(null);
    setDetailedSummaryError(null);
    setIsEditingText(false);
    setTextSaveError(null);
    setReextractError(null);
  }, [analysis?.storage_path]);

  if (!analysis)
    return (
      <Card className="analysis-placeholder">
        <FileSearch size={22} />
        <div>
          <h2>Analiz ayrıntıları</h2>
          <p>Üst veri ve mevzuat sonuçlarını görmek için bir evrak seçin.</p>
        </div>
      </Card>
    );

  const fieldKeys = Object.keys(LABELS) as Array<keyof EvrakFields>;

  const startEditing = () => {
    setSaveError(null);
    setDraft(
      Object.fromEntries(fieldKeys.map((key) => [key, toFormValue(analysis.fields[key])])),
    );
    setIsEditing(true);
  };

  const save = async () => {
    if (!onSave) return;
    setSaveError(null);
    const fields: EvrakFields = Object.fromEntries(
      fieldKeys.map((key) => [key, fromFormValue(key, draft[key] ?? "")]),
    );
    try {
      await onSave(fields);
      setIsEditing(false);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Alanlar kaydedilemedi.");
    }
  };

  const generateDetailedSummary = async () => {
    if (!onGenerateDetailedSummary) return;
    setDetailedSummaryError(null);
    try {
      await onGenerateDetailedSummary();
    } catch (error) {
      setDetailedSummaryError(
        error instanceof Error ? error.message : "Ayrıntılı özet oluşturulamadı.",
      );
    }
  };

  const startEditingText = () => {
    setTextSaveError(null);
    setTextDraft(documentText?.pages ?? []);
    setIsEditingText(true);
  };

  const saveText = async () => {
    if (!onSaveText) return;
    setTextSaveError(null);
    try {
      await onSaveText(textDraft);
      setIsEditingText(false);
    } catch (error) {
      setTextSaveError(error instanceof Error ? error.message : "Metin kaydedilemedi.");
    }
  };

  const reextractText = async () => {
    if (!onReextract) return;
    setReextractError(null);
    try {
      await onReextract();
    } catch (error) {
      setReextractError(
        error instanceof Error ? error.message : "Belge yeniden OCR ile işlenemedi.",
      );
    }
  };

  return (
    <Card className="analysis-panel">
      <div className="section-heading">
        <div>
          <h2>Analiz ayrıntıları</h2>
          <p>{analysis.file_name}</p>
        </div>
        <StatusBadge
          tone={
            analysis.compliance_status === "compliant" ? "success" : "warning"
          }
        >
          {analysis.compliance_status === "compliant"
            ? "Uygun"
            : analysis.compliance_status === "partially_compliant"
              ? "Kısmen uygun"
              : "Eksik"}
        </StatusBadge>
      </div>
      {(analysis.extraction.used_ocr ||
        (analysis.extraction.scrubbed_markers?.length ?? 0) > 0) && (
        <Alert variant="warning" icon={<AlertTriangle />}>
          {analysis.extraction.used_ocr
            ? "Evrak OCR ile okundu; çıkarılan alanları doğrulayın."
            : "Olası talimat enjeksiyonu işaretleri metinden temizlendi."}
        </Alert>
      )}
      {analysis.summary && (
        <details open>
          <summary>Evrak özeti</summary>
          <p className="document-summary-text">{analysis.summary}</p>
        </details>
      )}
      {onGenerateDetailedSummary && (
        <details>
          <summary>Detaylı özet</summary>
          <div className="detailed-summary-section">
            {detailedSummaryError && <Alert variant="error">{detailedSummaryError}</Alert>}
            {analysis.detailed_summary ? (
              <p className="document-summary-text document-summary-text-detailed">
                {analysis.detailed_summary}
              </p>
            ) : (
              <>
                <p className="detail-empty">
                  Belgenin tamamını kapsayan, cümle sayısı sınırı olmayan bir özet üretilebilir.
                  Uzun belgelerde üretim birkaç dakika sürebilir.
                </p>
                <Button loading={generatingDetailedSummary} onClick={() => void generateDetailedSummary()}>
                  Detaylı özet oluştur
                </Button>
              </>
            )}
          </div>
        </details>
      )}
      {analysis.guardrail && (
        <details open>
          <summary>Bilgi güvenliği</summary>
          <div className="guardrail-summary">
            <StatusBadge
              tone={
                analysis.guardrail.requires_human_review ? "danger" : "info"
              }
            >
              {SENSITIVITY_LABELS[analysis.guardrail.sensitivity_level]}
            </StatusBadge>
            {analysis.guardrail.requires_human_review && (
              <Alert variant="error" icon={<ShieldAlert />}>Bu evrak insan incelemesi gerektiriyor.</Alert>
            )}
            {analysis.guardrail.reasons.length > 0 && (
              <ul className="detail-list">
                {analysis.guardrail.reasons.map((reason, index) => (
                  <li key={`${reason}-${index}`}>{reason}</li>
                ))}
              </ul>
            )}
            {analysis.guardrail.pii_findings.length > 0 && (
              <ul className="detail-list pii-findings">
                {analysis.guardrail.pii_findings.map((finding, index) => (
                  <li key={`${finding.kind}-${index}`}>
                    <strong>{finding.kind.toLocaleUpperCase("tr-TR")}</strong>
                    <span>{finding.preview}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </details>
      )}
      {analysis.signature && (
        <details>
          <summary>İmza ve mühür</summary>
          <div className="guardrail-summary">
            <StatusBadge tone={analysis.signature.is_signed ? "success" : "warning"}>
              {analysis.signature.is_signed ? "İmzalı" : "İmza tespit edilmedi"}
            </StatusBadge>
            {analysis.signature.marks.length ? (
              <ul className="detail-list">
                {analysis.signature.marks.map((mark, index) => (
                  <li key={`${mark.kind}-${mark.page}-${index}`}>
                    <strong>{MARK_KIND_LABELS[mark.kind]}</strong>
                    <span>Sayfa {mark.page}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="detail-empty">
                Sayfada imza, mühür veya el yazısı bölgesi tespit edilmedi.
              </p>
            )}
            <small>
              Bu tespit sezgisel bir inceleme ipucudur; imza veya mührün gerçekliğine
              dair adli bir belirleme değildir.
            </small>
          </div>
        </details>
      )}
      <details open>
        <summary>
          <span>Üst veri alanları</span>
          {onSave && !isEditing && (
            <Button
              variant="ghost"
              size="sm"
              leadingIcon={<Pencil />}
              onClick={(event) => {
                event.preventDefault();
                startEditing();
              }}
            >
              Düzenle
            </Button>
          )}
        </summary>
        {isEditing ? (
          <div className="metadata-edit-form">
            {saveError && <Alert variant="error">{saveError}</Alert>}
            {fieldKeys.map((key) =>
              LIST_FIELDS.has(key) ? (
                <Textarea
                  key={key}
                  label={LABELS[key]}
                  rows={3}
                  value={draft[key] ?? ""}
                  helperText="Her satıra bir değer yazın."
                  onChange={(event) =>
                    setDraft((previous) => ({ ...previous, [key]: event.target.value }))
                  }
                />
              ) : (
                <Input
                  key={key}
                  label={LABELS[key]}
                  value={draft[key] ?? ""}
                  onChange={(event) =>
                    setDraft((previous) => ({ ...previous, [key]: event.target.value }))
                  }
                />
              ),
            )}
            <div className="metadata-edit-actions">
              <Button
                variant="ghost"
                leadingIcon={<X />}
                disabled={saving}
                onClick={() => {
                  setIsEditing(false);
                  setSaveError(null);
                }}
              >
                Vazgeç
              </Button>
              <Button loading={saving} onClick={() => void save()}>
                Kaydet
              </Button>
            </div>
          </div>
        ) : (
          <dl className="metadata-grid">
            {fieldKeys.map((key) => (
              <div key={key}>
                <dt>{LABELS[key]}</dt>
                <dd>{showValue(analysis.fields[key])}</dd>
              </div>
            ))}
          </dl>
        )}
      </details>
      {documentText && (
        <details>
          <summary>
            <span>Belge metni</span>
            {onSaveText && !isEditingText && (
              <Button
                variant="ghost"
                size="sm"
                leadingIcon={<Pencil />}
                onClick={(event) => {
                  event.preventDefault();
                  startEditingText();
                }}
              >
                Düzenle
              </Button>
            )}
          </summary>
          {isEditingText ? (
            <div className="metadata-edit-form">
              {textSaveError && <Alert variant="error">{textSaveError}</Alert>}
              {textDraft.map((page, index) => (
                <Textarea
                  key={index}
                  label={`Sayfa ${index + 1}/${textDraft.length}`}
                  rows={10}
                  value={page}
                  onChange={(event) =>
                    setTextDraft((previous) =>
                      previous.map((value, i) => (i === index ? event.target.value : value)),
                    )
                  }
                />
              ))}
              <div className="metadata-edit-actions">
                <Button
                  variant="ghost"
                  leadingIcon={<X />}
                  disabled={savingText}
                  onClick={() => {
                    setIsEditingText(false);
                    setTextSaveError(null);
                  }}
                >
                  Vazgeç
                </Button>
                <Button loading={savingText} onClick={() => void saveText()}>
                  Kaydet
                </Button>
              </div>
            </div>
          ) : (
            <div className="document-text-pages">
              {documentText.pages.map((page, index) => (
                <div key={index} className="document-text-page-block">
                  <h4>
                    Sayfa {index + 1}/{documentText.pages.length}
                  </h4>
                  <p className="document-text-page">{page}</p>
                </div>
              ))}
              {onReextract && (
                <div className="reextract-action">
                  <p className="detail-empty">
                    Belge, görüntü tabanlı bir yapay zeka modeliyle yeniden okunabilir. Bu
                    işlem birkaç dakika sürebilir.
                  </p>
                  {reextractError && <Alert variant="error">{reextractError}</Alert>}
                  <Button loading={reextracting} onClick={() => void reextractText()}>
                    Yeniden OCR
                  </Button>
                </div>
              )}
            </div>
          )}
        </details>
      )}
      <details>
        <summary>Eksik bilgiler ({analysis.missing_fields.length})</summary>
        {analysis.missing_fields.length ? (
          <ul className="detail-list">
            {analysis.missing_fields.map((item) => (
              <li key={item.key}>
                <strong>{item.label}</strong>
                <span>{item.reason || item.mevzuat}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="detail-empty">Zorunlu alanların tümü mevcut.</p>
        )}
      </details>
      <details>
        <summary>
          Mevzuat önerileri ({analysis.mevzuat_references.length})
        </summary>
        {analysis.mevzuat_references.length ? (
          <ul className="detail-list">
            {analysis.mevzuat_references.map((item, index) => (
              <li key={`${item.mevzuat}-${index}`}>
                <strong>{item.mevzuat}</strong>
                <span>{item.aciklama}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="detail-empty">Mevzuat önerisi bulunamadı.</p>
        )}
      </details>
    </Card>
  );
}
