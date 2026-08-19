import type { CSSProperties } from "react";

export interface ActivityPoint {
  label: string;
  documents: number;
  drafts: number;
}

export interface DistributionItem {
  label: string;
  value: number;
  tone: "blue" | "violet" | "emerald" | "amber";
}

type VariableStyle = CSSProperties & Record<`--${string}`, string | number>;

export function WeeklyActivityChart({ points }: { points: ActivityPoint[] }) {
  const maximum = Math.max(1, ...points.map((point) => point.documents + point.drafts));
  return (
    <div className="home-activity-chart" role="img" aria-label="Son yedi günlük evrak ve taslak hareketliliği">
      <div className="home-chart-grid" aria-hidden="true"><span /><span /><span /><span /></div>
      <div className="home-chart-bars">
        {points.map((point) => {
          const total = point.documents + point.drafts;
          const height = Math.max(total ? 12 : 3, Math.round((total / maximum) * 100));
          const documentShare = total ? Math.round((point.documents / total) * 100) : 0;
          return (
            <div className="home-chart-column" key={point.label} aria-label={`${point.label}: ${point.documents} evrak, ${point.drafts} taslak`}>
              <span className="home-stacked-bar" style={{ "--bar-height": `${height}%`, "--document-share": `${documentShare}%` } as VariableStyle}><i /><b /></span>
              <small>{point.label}</small>
            </div>
          );
        })}
      </div>
      <div className="home-chart-legend"><span className="is-documents">Evrak</span><span className="is-drafts">Taslak</span></div>
    </div>
  );
}

export function DocumentStatusChart({ ready, review, pending }: { ready: number; review: number; pending: number }) {
  const total = ready + review + pending;
  const readyAngle = total ? (ready / total) * 360 : 0;
  const reviewAngle = total ? ((ready + review) / total) * 360 : 0;
  const style = { "--ready-angle": `${readyAngle}deg`, "--review-angle": `${reviewAngle}deg` } as VariableStyle;
  return (
    <div className="home-status-chart">
      <div className={`home-donut${total ? "" : " is-empty"}`} style={style} role="img" aria-label={`${ready} hazır, ${review} inceleme gerekli, ${pending} analiz bekliyor`}><span><strong>{total}</strong><small>toplam</small></span></div>
      <dl>
        <div className="is-ready"><dt>Hazır</dt><dd>{ready}</dd></div>
        <div className="is-review"><dt>İncelenecek</dt><dd>{review}</dd></div>
        <div className="is-pending"><dt>Bekliyor</dt><dd>{pending}</dd></div>
      </dl>
    </div>
  );
}

export function TypeDistribution({ items }: { items: DistributionItem[] }) {
  const maximum = Math.max(1, ...items.map((item) => item.value));
  return (
    <div className="home-type-distribution">
      {items.map((item) => (
        <div key={item.label} className={`is-${item.tone}`}>
          <span><strong>{item.label}</strong><small>{item.value}</small></span>
          <i><b style={{ "--distribution-width": `${Math.max(5, Math.round((item.value / maximum) * 100))}%` } as VariableStyle} /></i>
        </div>
      ))}
    </div>
  );
}
