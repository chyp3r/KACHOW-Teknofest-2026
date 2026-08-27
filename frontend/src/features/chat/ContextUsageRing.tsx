import { useId } from "react";
import type { ContextUsage } from "../../types/chat";

// Claude'un bağlam göstergesi gibi: modelin bağlam penceresinin ne kadarının
// ne için dolu olduğunu gösteren küçük bir halka. Veri backend'den gelir
// (final_result.details.context_usage -> planning_graph._run_assist); yalnızca
// assist turları üretir, o yüzden `usage` null iken bileşen hiç render olmaz.

const SEGMENT_COLORS: Record<string, string> = {
  system: "var(--accent-blue)",
  document_context: "var(--accent-purple, #8b5cf6)",
  history_summary: "var(--accent-teal, #14b8a6)",
  history: "var(--accent-amber, #f59e0b)",
  input: "var(--accent-green, #22c55e)",
  reserved: "var(--text-muted)",
};

const RADIUS = 15;
const STROKE = 5;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function ContextUsageRing({ usage }: { usage: ContextUsage | null | undefined }) {
  const titleId = useId();
  if (!usage || usage.total <= 0) return null;

  const percent = Math.min(100, Math.round((usage.used / usage.total) * 100));
  const visible = usage.segments.filter((segment) => segment.tokens > 0);

  let offset = 0;
  const arcs = visible.map((segment) => {
    const fraction = Math.min(1, segment.tokens / usage.total);
    const length = fraction * CIRCUMFERENCE;
    const arc = (
      <circle
        key={segment.key}
        cx="18"
        cy="18"
        r={RADIUS}
        fill="none"
        stroke={SEGMENT_COLORS[segment.key] ?? "var(--accent-blue)"}
        strokeWidth={STROKE}
        strokeDasharray={`${length} ${CIRCUMFERENCE - length}`}
        strokeDashoffset={-offset}
      />
    );
    offset += length;
    return arc;
  });

  return (
    <details className="context-usage">
      <summary aria-label={`Bağlam penceresi: %${percent} dolu`}>
        <svg
          className="context-usage-ring"
          width="36"
          height="36"
          viewBox="0 0 36 36"
          role="img"
          aria-labelledby={titleId}
        >
          <title id={titleId}>Bağlam penceresi %{percent} dolu</title>
          <circle
            cx="18"
            cy="18"
            r={RADIUS}
            fill="none"
            stroke="var(--border-default)"
            strokeWidth={STROKE}
          />
          <g transform="rotate(-90 18 18)">{arcs}</g>
          <text
            x="18"
            y="18"
            className="context-usage-percent"
            fontSize="9"
            fontWeight="600"
          >
            %{percent}
          </text>
        </svg>
        <span className="context-usage-caption">
          Bağlam · {usage.used.toLocaleString("tr-TR")} / {usage.total.toLocaleString("tr-TR")} token
        </span>
      </summary>
      <div className="context-usage-breakdown">
        <ul>
          {visible.map((segment) => (
            <li key={segment.key}>
              <span
                className="context-usage-swatch"
                style={{ background: SEGMENT_COLORS[segment.key] ?? "var(--accent-blue)" }}
                aria-hidden="true"
              />
              <span className="context-usage-label">{segment.label}</span>
              <span className="context-usage-value">
                {segment.tokens.toLocaleString("tr-TR")} token ·{" "}
                %{Math.round((segment.tokens / usage.total) * 100)}
              </span>
            </li>
          ))}
          <li>
            <span
              className="context-usage-swatch"
              style={{ background: "var(--border-default)" }}
              aria-hidden="true"
            />
            <span className="context-usage-label">Boş</span>
            <span className="context-usage-value">
              {usage.free.toLocaleString("tr-TR")} token ·{" "}
              %{Math.round((usage.free / usage.total) * 100)}
            </span>
          </li>
        </ul>
      </div>
    </details>
  );
}
