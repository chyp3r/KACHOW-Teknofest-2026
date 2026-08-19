import kachowMark from "../assets/kachow-mark.svg";

export function BrandLockup({ compact = false }: { compact?: boolean }) {
  return (
    <div
      className={`brand-lockup ${compact ? "brand-lockup-compact" : ""}`.trim()}
      aria-label={compact ? "KACHOW Karar Destek Sistemi" : undefined}
    >
      <img className="brand-symbol" src={kachowMark} alt="" aria-hidden="true" />
      <span className="brand-lockup-copy">
        <strong>KACHOW</strong>
        <small>Karar Destek Sistemi</small>
      </span>
    </div>
  );
}
