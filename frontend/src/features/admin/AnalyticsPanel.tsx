import { useQuery } from "@tanstack/react-query";
import { Activity, BarChart3, ExternalLink, ShieldAlert, Users } from "lucide-react";
import { ApiErrorNotice } from "../../components/ApiErrorNotice";
import { StatusBadge } from "../../components/StatusBadge";
import { Card, Spinner } from "../../components/Surface";
import { useCompanyAnalytics } from "../../hooks/useCompanyAnalytics";
import { queryKeys } from "../../query/queryKeys";
import { analyticsService } from "../../services/analyticsService";
import type { TimeseriesPoint } from "../../types/management";

const DECISION_LABELS: Record<string, string> = {
  block: "Engellendi",
  allow: "İzin verildi",
  permit: "İzin verildi",
  warn: "Uyarı",
  flagged: "İşaretlendi",
  passed: "Geçti",
  redacted: "Maskelendi",
  blocked: "Engellendi",
  needs_review: "İnsan incelemesi gerekli",
};
const STAGE_LABELS: Record<string, string> = { input: "Girdi kontrolü", output: "Çıktı kontrolü", retrieval: "Bilgi erişimi", tool: "Araç kullanımı" };
const STAGE_CONTEXTS: Record<string, string> = {
  input: "Belge sisteme alınırken",
  output: "Yanıt kullanıcıya gösterilmeden önce",
  retrieval: "Bilgi kaynakları aranırken",
  tool: "Bir araç çalıştırılırken",
};
const KIND_LABELS: Record<string, string> = {
  pii: "Kişisel veri",
  prompt_injection: "Prompt enjeksiyonu",
  policy: "Politika",
  clearance: "Yetki seviyesi",
  content: "İçerik güvenliği",
  sensitivity: "Hassasiyet",
  groundedness: "Kaynak dayanağı",
  llm_judge: "Yapay zekâ değerlendirmesi",
};
const KIND_DESCRIPTIONS: Record<string, string> = {
  pii: "kişisel veri bulunup bulunmadığı denetlendi",
  prompt_injection: "zararlı veya yönlendirici talimat izleri arandı",
  policy: "kurum güvenlik politikalarına uygunluk denetlendi",
  clearance: "erişim yetkisinin yeterli olup olmadığı denetlendi",
  content: "içeriğin güvenli kullanım koşullarına uygunluğu denetlendi",
  sensitivity: "belgenin gizlilik ve hassasiyet düzeyi değerlendirildi",
  groundedness: "çıktıdaki iddiaların kaynaklarla desteklenip desteklenmediği denetlendi",
  llm_judge: "çıktının kalite ve güvenlik ölçütlerine uygunluğu değerlendirildi",
};
const DECISION_DESCRIPTIONS: Record<string, string> = {
  block: "İşlem güvenlik nedeniyle durduruldu.",
  blocked: "İşlem güvenlik nedeniyle durduruldu.",
  allow: "Kontrol başarıyla tamamlandı; ek işlem gerekmiyor.",
  permit: "Kontrol başarıyla tamamlandı; ek işlem gerekmiyor.",
  passed: "Kontrol başarıyla tamamlandı; ek işlem gerekmiyor.",
  warn: "Dikkat gerektiren bir güvenlik sinyali kaydedildi.",
  flagged: "İncelenmesi gereken bir güvenlik sinyali kaydedildi.",
  redacted: "Tespit edilen hassas bölüm güvenli biçimde maskelendi.",
  needs_review: "Otomatik karar kesinleşmedi; yetkili bir kullanıcının değerlendirmesi gerekiyor.",
};
const RUN_STATUS_LABELS: Record<string, string> = {
  rejected: "Reddedildi",
  failed: "Başarısız",
  completed: "Tamamlandı",
  revise_requested: "Revizyon istendi",
  needs_human_approval: "İnsan onayı gerekli",
  running: "Çalışıyor",
};

function label(value: string, labels: Record<string, string>) {
  return labels[value.toLocaleLowerCase("tr-TR")] ?? value.replace(/_/g, " ");
}

function guardrailDescription(stage: string, kind: string, decision: string) {
  const normalizedStage = stage.toLocaleLowerCase("tr-TR");
  const normalizedKind = kind.toLocaleLowerCase("tr-TR");
  const normalizedDecision = decision.toLocaleLowerCase("tr-TR");
  const stageContext = STAGE_CONTEXTS[normalizedStage] ?? `${label(stage, STAGE_LABELS)} sırasında`;
  const kindDescription = KIND_DESCRIPTIONS[normalizedKind] ?? `${label(kind, KIND_LABELS).toLocaleLowerCase("tr-TR")} denetlendi`;
  const decisionDescription = DECISION_DESCRIPTIONS[normalizedDecision] ?? `${label(decision, DECISION_LABELS)} kararı kaydedildi.`;

  return `${stageContext} ${kindDescription}. ${decisionDescription}`;
}

function MiniBars({ points, empty }: { points: TimeseriesPoint[]; empty: string }) {
  if (!points.length) return <p className="detail-empty">{empty}</p>;
  const max = Math.max(1, ...points.map((point) => point.count));
  return <div className="analytics-mini-bars" aria-label={empty}>{points.map((point) => <div key={point.bucket} title={`${new Date(point.bucket).toLocaleDateString("tr-TR")}: ${point.count}`}><span style={{ height: `${Math.max(6, (point.count / max) * 100)}%` }} /><small>{new Date(point.bucket).toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit" })}</small></div>)}</div>;
}

export function AnalyticsPanel({
  companyId,
  canViewObservability,
}: {
  companyId: string;
  canViewObservability: boolean;
}) {
  const analytics = useCompanyAnalytics(companyId, 30);
  const guardrails = useQuery({ queryKey: queryKeys.analyticsGuardrails(companyId), queryFn: () => analyticsService.guardrails(companyId) });
  const links = useQuery({
    queryKey: queryKeys.analyticsLinks(companyId),
    queryFn: () => analyticsService.links(companyId),
    enabled: canViewObservability,
  });
  const summary = analytics.summary;
  const runEntries = Object.entries(summary?.run_status ?? {});
  const totalRuns = runEntries.reduce((total, [, count]) => total + count, 0);
  const failedRuns = runEntries.filter(([status]) => /fail|error|cancel/i.test(status)).reduce((total, [, count]) => total + count, 0);
  const successRate = totalRuns ? Math.round(((totalRuns - failedRuns) / totalRuns) * 100) : 0;
  const maxGuardrailCount = Math.max(1, ...(guardrails.data ?? []).map((item) => item.count));
  if (analytics.loading) return <div className="table-loading"><Spinner />Analitikler yükleniyor…</div>;
  return <div className="admin-section">
    <ApiErrorNotice error={(analytics.error ?? guardrails.error ?? links.error) || null} />
    <div className="admin-overview-grid"><Card className="admin-metric-card"><span><BarChart3 /></span><div><small>Toplam evrak</small><strong>{summary?.document_count ?? 0}</strong></div></Card><Card className="admin-metric-card"><span><Activity /></span><div><small>AI iş akışı</small><strong>{totalRuns}</strong><small>%{successRate} başarılı</small></div></Card><Card className="admin-metric-card"><span><Users /></span><div><small>7 günlük aktif kullanıcı</small><strong>{summary?.active_users_7d ?? 0}</strong></div></Card><Card className="admin-metric-card"><span><ShieldAlert /></span><div><small>Engellenen işlem</small><strong>{summary?.guardrail_blocked_total ?? 0}</strong></div></Card></div>
    <div className="management-two-column"><Card className="management-panel"><header className="management-panel-header"><div><h2>AI iş akışı</h2><p>Son 30 gündeki çalıştırma hacmi</p></div></header><MiniBars points={analytics.runTimeseries} empty="İş akışı verisi bulunmuyor." /><div className="analytics-status-row">{runEntries.map(([status, count]) => <StatusBadge key={status} tone={/fail|error|cancel/i.test(status) ? "danger" : /complete|success/i.test(status) ? "success" : "info"}>{`${label(status, RUN_STATUS_LABELS)}: ${count}`}</StatusBadge>)}</div></Card><Card className="management-panel"><header className="management-panel-header"><div><h2>Güvenlik akışı</h2><p>Son 30 gündeki engelleme olayları</p></div></header><MiniBars points={analytics.guardrailTimeseries} empty="Engelleme verisi bulunmuyor." /></Card></div>
    <div className="management-two-column"><Card className="management-panel"><header className="management-panel-header"><div><h2>Birim hareketliliği</h2><p>Yönlendirilmiş taslak hacmi</p></div></header><ul className="management-list">{analytics.units.map((unit) => <li key={unit.unit_id ?? unit.destination ?? "unknown"}><div><strong>{unit.destination ?? "Belirtilmemiş"}</strong><small>{unit.count} işlem</small></div></li>)}</ul></Card><Card className="management-panel"><header className="management-panel-header"><div><h2>Güvenlik kararları</h2><p>Her kontrolün aşaması, bulgusu, sonucu ve toplam görülme sayısı</p></div></header>{guardrails.data?.length ? <ul className="management-list guardrail-breakdown">{guardrails.data.map((item, index) => <li key={`${item.stage}-${item.kind}-${item.decision}-${index}`}><div><strong>{label(item.kind, KIND_LABELS)}</strong><small>{label(item.stage, STAGE_LABELS)}</small><p className="guardrail-description">{guardrailDescription(item.stage, item.kind, item.decision)}</p><span className="analytics-distribution"><i style={{ width: `${(item.count / maxGuardrailCount) * 100}%` }} /></span></div><StatusBadge tone={["block", "blocked"].includes(item.decision) ? "danger" : item.decision === "needs_review" ? "warning" : "info"}>{`${label(item.decision, DECISION_LABELS)} · ${item.count}`}</StatusBadge></li>)}</ul> : <p className="detail-empty">Güvenlik kararı bulunmuyor.</p>}</Card></div>
    {canViewObservability && links.data && <Card className="management-panel"><header className="management-panel-header"><div><h2>İlişkiler ve gözlemlenebilirlik</h2><p>Şirket filtresi uygulanmış teknik görünümler.</p></div></header><div className="management-link-row"><a href={links.data.grafana_url} target="_blank" rel="noreferrer">Grafana panosunu aç <ExternalLink /></a><a href={links.data.langfuse_url} target="_blank" rel="noreferrer">Langfuse izlerini aç <ExternalLink /></a></div></Card>}
  </div>;
}
