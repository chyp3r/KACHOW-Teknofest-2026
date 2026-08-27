import { Activity, TrendingUp, UserPlus, Users } from "lucide-react";
import { Card, Spinner } from "../../components/Surface";
import { StatusBadge } from "../../components/StatusBadge";
import type { RootUserInsights } from "../../types/management";
import { guardrailDecisionLabel } from "../chat/guardrailLabels";
import { agentLabel, intentLabel, roleLabel, runStatusLabel, tokenKindLabel } from "./labels";

const ROLE_TONES = ["var(--accent-blue)", "var(--accent-violet)", "var(--accent-emerald)", "var(--accent-amber)", "var(--accent-rose)", "var(--accent-cyan)"];

function nf(value: number): string {
  return new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 0 }).format(value);
}

function ratio(value: number): string {
  return new Intl.NumberFormat("tr-TR", { style: "percent", maximumFractionDigits: 0 }).format(value);
}

function relTime(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "az önce";
  if (mins < 60) return `${mins} dk önce`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} sa önce`;
  const days = Math.round(hrs / 24);
  if (days < 30) return `${days} gün önce`;
  return new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short" }).format(new Date(iso));
}

/** Bars = gün başına iş akışı; çizgi = gün başına aktif kullanıcı. */
function ActivityTimeline({ points }: { points: RootUserInsights["daily_activity"] }) {
  if (points.length === 0) {
    return <p className="detail-empty">Son 30 günde iş akışı kaydı yok.</p>;
  }
  const w = 720;
  const h = 160;
  const pad = 8;
  const maxRuns = Math.max(1, ...points.map((p) => p.runs));
  const maxUsers = Math.max(1, ...points.map((p) => p.active_users));
  const step = (w - pad * 2) / Math.max(points.length, 1);
  const barW = Math.max(2, step * 0.55);
  const linePoints = points
    .map((p, i) => {
      const x = pad + i * step + step / 2;
      const y = h - pad - (p.active_users / maxUsers) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <div className="platform-timeline">
      <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Son 30 gün gün başına iş akışı ve aktif kullanıcı" preserveAspectRatio="none">
        {points.map((p, i) => {
          const x = pad + i * step + (step - barW) / 2;
          const barH = (p.runs / maxRuns) * (h - pad * 2);
          return (
            <rect
              key={p.date}
              x={x.toFixed(1)}
              y={(h - pad - barH).toFixed(1)}
              width={barW.toFixed(1)}
              height={Math.max(barH, p.runs ? 2 : 0).toFixed(1)}
              rx="1.5"
              className="platform-timeline-bar"
            >
              <title>{`${new Date(p.date).toLocaleDateString("tr-TR")}: ${p.runs} iş akışı, ${p.active_users} aktif kullanıcı`}</title>
            </rect>
          );
        })}
        <polyline points={linePoints} className="platform-timeline-line" fill="none" />
      </svg>
      <div className="platform-timeline-legend">
        <span className="is-runs">İş akışı / gün</span>
        <span className="is-users">Aktif kullanıcı / gün</span>
      </div>
    </div>
  );
}

function RoleDonut({ byRole }: { byRole: Record<string, number> }) {
  const entries = Object.entries(byRole).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, value]) => sum + value, 0);
  const size = 132;
  const r = 52;
  const cx = size / 2;
  const cy = size / 2;
  const circ = 2 * Math.PI * r;
  let offset = 0;

  return (
    <div className="platform-donut">
      <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Rol dağılımı">
        <circle cx={cx} cy={cy} r={r} className="platform-donut-track" fill="none" />
        {total > 0 &&
          entries.map(([role, value], index) => {
            const len = (value / total) * circ;
            const seg = (
              <circle
                key={role}
                cx={cx}
                cy={cy}
                r={r}
                fill="none"
                stroke={ROLE_TONES[index % ROLE_TONES.length]}
                strokeWidth="14"
                strokeDasharray={`${len} ${circ - len}`}
                strokeDashoffset={-offset}
                transform={`rotate(-90 ${cx} ${cy})`}
              />
            );
            offset += len;
            return seg;
          })}
        <text x={cx} y={cy - 2} className="platform-donut-total" textAnchor="middle">{nf(total)}</text>
        <text x={cx} y={cy + 14} className="platform-donut-caption" textAnchor="middle">kullanıcı</text>
      </svg>
      <ul className="platform-donut-legend">
        {entries.map(([role, value], index) => (
          <li key={role}>
            <span className="platform-swatch" style={{ background: ROLE_TONES[index % ROLE_TONES.length] }} />
            <span>{roleLabel(role)}</span>
            <strong>{nf(value)}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DistributionBars({
  data,
  label,
  tone = "var(--accent-blue)",
}: {
  data: Record<string, number>;
  label: (key: string) => string;
  tone?: string;
}) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, value]) => value));
  if (entries.length === 0) {
    return <p className="detail-empty">Kayıt yok.</p>;
  }
  return (
    <ul className="platform-dist">
      {entries.map(([key, value]) => (
        <li key={key}>
          <span className="platform-dist-label">{label(key)}</span>
          <span className="platform-dist-track">
            <span className="platform-dist-fill" style={{ width: `${(value / max) * 100}%`, background: tone }} />
          </span>
          <strong>{nf(value)}</strong>
        </li>
      ))}
    </ul>
  );
}

export function PlatformUserInsights({
  data,
  loading,
}: {
  data: RootUserInsights | undefined;
  loading: boolean;
}) {
  if (loading || !data) {
    return (
      <div className="table-loading">
        <Spinner />
        Kullanıcı istatistikleri yükleniyor…
      </div>
    );
  }

  const k = data.kpis;

  return (
    <div className="admin-section platform-insights">
      <div className="platform-kpi-row">
        <Card className="platform-kpi"><span><Users /></span><div><small>Toplam kullanıcı</small><strong>{nf(k.total_users)}</strong></div></Card>
        <Card className="platform-kpi"><span><Activity /></span><div><small>30 günde aktif</small><strong>{nf(k.active_30d)}</strong><em>7 günde {nf(k.active_7d)}</em></div></Card>
        <Card className="platform-kpi"><span><TrendingUp /></span><div><small>Aktiflik oranı (30g)</small><strong>{ratio(k.activity_rate_30d)}</strong><em>kullanıcı başına {new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 1 }).format(k.runs_per_active_user_30d)} iş akışı</em></div></Card>
        <Card className="platform-kpi"><span><UserPlus /></span><div><small>Yeni kullanıcı (30g)</small><strong>{nf(k.new_30d)}</strong><em>7 günde {nf(k.new_7d)}</em></div></Card>
        <Card className="platform-kpi"><span><Activity /></span><div><small>Toplam iş akışı</small><strong>{nf(k.total_runs)}</strong></div></Card>
      </div>

      <Card className="management-panel">
        <header className="management-panel-header"><div><h2>Aktiflik zaman serisi</h2><p>Son 30 gün — gün başına iş akışı ve aktif kullanıcı</p></div></header>
        <ActivityTimeline points={data.daily_activity} />
      </Card>

      <div className="platform-two-col">
        <Card className="management-panel">
          <header className="management-panel-header"><div><h2>Rol dağılımı</h2></div></header>
          <RoleDonut byRole={data.by_role} />
        </Card>
        <Card className="management-panel">
          <header className="management-panel-header"><div><h2>Kurum bazında koltuklar</h2><p>Kurum başına kullanıcı sayısı</p></div></header>
          <ul className="management-list">
            {data.seats_by_company.map((seat) => (
              <li key={seat.company_id}>
                <div><strong>{seat.name}</strong><small>{seat.is_active ? "Aktif" : "Pasif"}</small></div>
                <StatusBadge tone={seat.is_active ? "success" : "neutral"}>{`${nf(seat.user_count)} kullanıcı`}</StatusBadge>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card className="management-panel">
        <header className="management-panel-header"><div><h2>En aktif kullanıcılar</h2><p>İş akışı sayısına göre ilk {data.top_users.length}</p></div></header>
        <div className="platform-table-wrap">
          <table className="platform-table">
            <thead>
              <tr><th>Kullanıcı</th><th>Kurum</th><th>Rol</th><th>İş akışı</th><th>Taslak</th><th>Evrak</th><th>Sohbet</th><th>Son etkinlik</th></tr>
            </thead>
            <tbody>
              {data.top_users.map((user) => (
                <tr key={user.user_id}>
                  <td>{user.username}</td>
                  <td>{user.company_name ?? "—"}</td>
                  <td>{roleLabel(user.role)}</td>
                  <td>{nf(user.run_count)}</td>
                  <td>{nf(user.draft_count)}</td>
                  <td>{nf(user.document_count)}</td>
                  <td>{nf(user.session_count)}</td>
                  <td>{relTime(user.last_seen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="platform-three-col">
        <Card className="management-panel">
          <header className="management-panel-header"><div><h2>İş akışı türü</h2></div></header>
          <DistributionBars data={data.runs_by_intent} label={intentLabel} tone="var(--accent-blue)" />
        </Card>
        <Card className="management-panel">
          <header className="management-panel-header"><div><h2>İş akışı sonucu</h2></div></header>
          <DistributionBars data={data.runs_by_status} label={runStatusLabel} tone="var(--accent-violet)" />
        </Card>
        <Card className="management-panel">
          <header className="management-panel-header"><div><h2>Güvenlik sinyalleri</h2><p>Guardrail kararları</p></div></header>
          <DistributionBars data={data.guardrail_by_decision} label={guardrailDecisionLabel} tone="var(--accent-amber)" />
        </Card>
      </div>

      <Card className="management-panel">
        <header className="management-panel-header">
          <div><h2>AI token kullanımı</h2><p>Sistem geneli — ajan ve tür bazında (Prometheus)</p></div>
          <StatusBadge tone={data.token_usage.available ? "success" : "neutral"}>
            {data.token_usage.available ? `${nf(data.token_usage.total)} token` : "Veri yok"}
          </StatusBadge>
        </header>
        {data.token_usage.available ? (
          <div className="platform-two-col">
            <div>
              <h3 className="platform-subhead">Ajan bazında</h3>
              <DistributionBars data={data.token_usage.by_agent} label={agentLabel} tone="var(--accent-emerald)" />
            </div>
            <div>
              <h3 className="platform-subhead">Tür bazında</h3>
              <DistributionBars data={data.token_usage.by_kind} label={tokenKindLabel} tone="var(--accent-cyan)" />
            </div>
          </div>
        ) : (
          <p className="detail-empty">Prometheus'a ulaşılamadı; token dökümü şu an gösterilemiyor.</p>
        )}
      </Card>
    </div>
  );
}
