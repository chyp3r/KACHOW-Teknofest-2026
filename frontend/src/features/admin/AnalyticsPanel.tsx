import { useQuery } from "@tanstack/react-query";
import { Activity, BarChart3, ExternalLink, ShieldAlert, Users } from "lucide-react";
import { ApiErrorNotice } from "../../components/ApiErrorNotice";
import { StatusBadge } from "../../components/StatusBadge";
import { Card, Spinner } from "../../components/Surface";
import { useCompanyAnalytics } from "../../hooks/useCompanyAnalytics";
import { queryKeys } from "../../query/queryKeys";
import { analyticsService } from "../../services/analyticsService";

export function AnalyticsPanel({ companyId }: { companyId: string }) {
  const analytics = useCompanyAnalytics(companyId, 30);
  const guardrails = useQuery({ queryKey: queryKeys.analyticsGuardrails(companyId), queryFn: () => analyticsService.guardrails(companyId) });
  const links = useQuery({ queryKey: queryKeys.analyticsLinks(companyId), queryFn: () => analyticsService.links(companyId) });
  const summary = analytics.summary;
  if (analytics.loading) return <div className="table-loading"><Spinner />Analitikler yükleniyor…</div>;
  return <div className="admin-section">
    <ApiErrorNotice error={(analytics.error ?? guardrails.error ?? links.error) || null} />
    <div className="admin-overview-grid"><Card className="admin-metric-card"><span><BarChart3 /></span><div><small>Evraklar</small><strong>{summary?.document_count ?? 0}</strong></div></Card><Card className="admin-metric-card"><span><Activity /></span><div><small>Taslaklar</small><strong>{summary?.draft_stats.total ?? 0}</strong></div></Card><Card className="admin-metric-card"><span><Users /></span><div><small>7 günlük aktif kullanıcı</small><strong>{summary?.active_users_7d ?? 0}</strong></div></Card><Card className="admin-metric-card"><span><ShieldAlert /></span><div><small>Engellenen işlem</small><strong>{summary?.guardrail_blocked_total ?? 0}</strong></div></Card></div>
    <div className="management-two-column"><Card className="management-panel"><header className="management-panel-header"><div><h2>Birim hareketliliği</h2><p>Yönlendirilmiş taslak hacmi</p></div></header><ul className="management-list">{analytics.units.map((unit) => <li key={unit.unit_id ?? unit.destination ?? "unknown"}><div><strong>{unit.destination ?? "Belirtilmemiş"}</strong><small>{unit.count} işlem</small></div></li>)}</ul></Card><Card className="management-panel"><header className="management-panel-header"><div><h2>Güvenlik kararları</h2><p>Guardrail aşaması ve karar dağılımı</p></div></header>{guardrails.data?.length ? <ul className="management-list">{guardrails.data.map((item, index) => <li key={`${item.stage}-${item.kind}-${item.decision}-${index}`}><div><strong>{item.kind}</strong><small>{item.stage}</small></div><StatusBadge tone={item.decision === "block" ? "danger" : "info"}>{`${item.decision} · ${item.count}`}</StatusBadge></li>)}</ul> : <p className="detail-empty">Guardrail olayı bulunmuyor.</p>}</Card></div>
    {links.data && <Card className="management-panel"><header className="management-panel-header"><div><h2>İlişkiler ve gözlemlenebilirlik</h2><p>Şirket filtresi uygulanmış teknik görünümler.</p></div></header><div className="management-link-row"><a href={links.data.grafana_url} target="_blank" rel="noreferrer">Grafana panosunu aç <ExternalLink /></a><a href={links.data.langfuse_url} target="_blank" rel="noreferrer">Langfuse izlerini aç <ExternalLink /></a></div></Card>}
  </div>;
}
