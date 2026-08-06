import { AlertTriangle, FileSearch } from "lucide-react";
import { StatusBadge } from "../../components/StatusBadge";
import type { DocumentAnalysis, EvrakFields } from "../../types/documents";

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
const showValue = (value: unknown) =>
  Array.isArray(value)
    ? value.join(", ") || "—"
    : value === null || value === undefined || value === ""
      ? "—"
      : String(value);

export function DocumentAnalysisPanel({
  analysis,
}: {
  analysis: DocumentAnalysis | null;
}) {
  if (!analysis)
    return (
      <section className="surface analysis-placeholder">
        <FileSearch size={22} />
        <div>
          <h2>Analiz ayrıntıları</h2>
          <p>Üst veri ve mevzuat sonuçlarını görmek için bir evrak seçin.</p>
        </div>
      </section>
    );
  return (
    <section className="surface analysis-panel">
      <div className="section-heading">
        <div>
          <h2>Analiz ayrıntıları</h2>
          <p>{analysis.file_name}</p>
        </div>
        <StatusBadge
          tone={
            analysis.compliance_status === "COMPLIANT" ? "success" : "warning"
          }
        >
          {analysis.compliance_status === "COMPLIANT"
            ? "Uygun"
            : "Kontrol gerekli"}
        </StatusBadge>
      </div>
      {(analysis.extraction.used_ocr ||
        (analysis.extraction.scrubbed_markers?.length ?? 0) > 0) && (
        <div className="notice warning">
          <AlertTriangle size={17} />
          <span>
            {analysis.extraction.used_ocr
              ? "Evrak OCR ile okundu; çıkarılan alanları doğrulayın."
              : "Olası talimat enjeksiyonu işaretleri metinden temizlendi."}
          </span>
        </div>
      )}
      <details open>
        <summary>Üst veri alanları</summary>
        <dl className="metadata-grid">
          {(Object.keys(LABELS) as Array<keyof EvrakFields>).map((key) => (
            <div key={key}>
              <dt>{LABELS[key]}</dt>
              <dd>{showValue(analysis.fields[key])}</dd>
            </div>
          ))}
        </dl>
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
    </section>
  );
}
