import { Loader2, Minimize2 } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { ContextUsage } from "../../types/chat";

// Claude'un çalışma modu altındaki bağlam göstergesi gibi: sadece küçük bir
// halka. Tıklanınca kırılımı + "Bağlamı sıkıştır" düğmesini taşıyan dar bir
// popup açılır. Veri backend'den gelir (details.context_usage ->
// planning_graph._run_assist / ChatService.compact_session). Değer değişince
// halka ve yüzde animasyonlu yükselir/iner.

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
const TWEEN_MS = 600;

const easeOutCubic = (t: number) => 1 - (1 - t) ** 3;

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** `target`'a doğru yumuşakça animasyonla ilerleyen bir sayı döndürür.
 * İlk montajda 0'dan başlar (sayaç yukarı doğru sayar). */
function useTweenedNumber(target: number): number {
  const [value, setValue] = useState(0);
  const fromRef = useRef(0);
  const frameRef = useRef<number>();

  useEffect(() => {
    if (prefersReducedMotion()) {
      setValue(target);
      return;
    }
    const from = fromRef.current;
    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / TWEEN_MS);
      const next = from + (target - from) * easeOutCubic(progress);
      setValue(next);
      fromRef.current = next;
      if (progress < 1) frameRef.current = requestAnimationFrame(tick);
    };
    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
    };
  }, [target]);

  return value;
}

export function ContextUsageRing({
  usage,
  onCompact,
  compacting = false,
}: {
  usage: ContextUsage | null | undefined;
  onCompact?: () => void | Promise<void>;
  compacting?: boolean;
}) {
  const titleId = useId();
  const total = usage && usage.total > 0 ? usage.total : 1;
  const targetPercent = usage ? Math.min(100, (usage.used / total) * 100) : 0;
  const animatedPercent = useTweenedNumber(targetPercent);

  const [drawn, setDrawn] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setDrawn(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!usage || usage.total <= 0) return null;

  const shownPercent = Math.round(animatedPercent);
  const visible = usage.segments.filter((segment) => segment.tokens > 0);

  let offset = 0;
  const arcs = visible.map((segment) => {
    const fraction = Math.min(1, segment.tokens / usage.total);
    const length = drawn ? fraction * CIRCUMFERENCE : 0;
    const arc = (
      <circle
        key={segment.key}
        className="context-usage-arc"
        cx="18"
        cy="18"
        r={RADIUS}
        fill="none"
        stroke={SEGMENT_COLORS[segment.key] ?? "var(--accent-blue)"}
        strokeWidth={STROKE}
        strokeDasharray={`${length} ${CIRCUMFERENCE - length}`}
        strokeDashoffset={drawn ? -offset : 0}
      />
    );
    offset += drawn ? fraction * CIRCUMFERENCE : 0;
    return arc;
  });

  const ring = (
    <svg
      className="context-usage-ring"
      width="30"
      height="30"
      viewBox="0 0 36 36"
      role="img"
      aria-labelledby={titleId}
    >
      <title id={titleId}>Bağlam penceresi %{shownPercent} dolu</title>
      <circle
        cx="18"
        cy="18"
        r={RADIUS}
        fill="none"
        stroke="var(--border-default)"
        strokeWidth={STROKE}
      />
      <g transform="rotate(-90 18 18)">{arcs}</g>
      <text x="18" y="18" className="context-usage-percent" fontSize="10" fontWeight="600">
        {shownPercent}
      </text>
    </svg>
  );

  return (
    <div className="context-usage" ref={rootRef}>
      <button
        type="button"
        className="context-usage-trigger"
        aria-label={`Bağlam penceresi: %${shownPercent} dolu`}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((value) => !value)}
      >
        {ring}
      </button>

      {open && (
        <div className="context-usage-popover" role="dialog" aria-label="Bağlam penceresi kullanımı">
          <header>
            <strong>Bağlam penceresi</strong>
            <span>
              %{shownPercent} · {usage.used.toLocaleString("tr-TR")} /{" "}
              {usage.total.toLocaleString("tr-TR")} token
            </span>
          </header>
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
                %{Math.round((usage.free / usage.total) * 100)}
              </span>
            </li>
          </ul>
          {onCompact && (
            <button
              type="button"
              className="context-usage-compact"
              disabled={compacting}
              onClick={() => {
                void onCompact();
                setOpen(false);
              }}
            >
              {compacting ? (
                <Loader2 size={13} className="context-usage-spinner" />
              ) : (
                <Minimize2 size={13} />
              )}
              {compacting ? "Sıkıştırılıyor…" : "Bağlamı sıkıştır"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
