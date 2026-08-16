import { AlertTriangle, FileSearch, Pencil, ShieldAlert, X } from "lucide-react";
import { useEffect, useState } from "react";
import { StatusBadge } from "../../components/StatusBadge";
import { Alert, Card } from "../../components/Surface";
import { Button } from "../../components/Button";
import { Input, Textarea } from "../../components/FormControls";
import type { DocumentAnalysis, EvrakFields } from "../../types/documents";
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
}: {
  analysis: DocumentAnalysis | null;
  // Undefined when the caller doesn't wire editing (e.g. no permission
  // hook available) -- the panel then stays read-only exactly as before.
  onSave?: (fields: EvrakFields) => Promise<void>;
  saving?: boolean;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saveError, setSaveError] = useState<string | null>(null);

  // A different document (or a fresh save) must never keep a stale edit
  // session open on top of it.
  useEffect(() => {
    setIsEditing(false);
    setSaveError(null);
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
