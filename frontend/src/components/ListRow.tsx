import { ChevronDown, ChevronUp } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

export const ListRow = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & {
  leading?: ReactNode;
  primary: ReactNode;
  secondary?: ReactNode;
  metadata?: ReactNode;
  status?: ReactNode;
  trailing?: ReactNode;
  selected?: boolean;
  expandable?: boolean;
}>(function ListRow({ leading, primary, secondary, metadata, status, trailing, selected, expandable, className = "", ...props }, ref) {
  return (
    <button ref={ref} type="button" className={`list-row ${selected ? "is-selected" : ""} ${className}`.trim()} aria-expanded={expandable === undefined ? undefined : selected} {...props}>
      {leading && <span className="list-row-leading" aria-hidden="true">{leading}</span>}
      <span className="list-row-content"><strong>{primary}</strong>{secondary && <span>{secondary}</span>}</span>
      {metadata && <span className="list-row-metadata">{metadata}</span>}
      {status && <span className="list-row-status">{status}</span>}
      {trailing ?? (expandable && <span className="list-row-trailing" aria-hidden="true">{selected ? <ChevronUp /> : <ChevronDown />}</span>)}
    </button>
  );
});
