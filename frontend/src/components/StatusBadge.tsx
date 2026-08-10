export type StatusTone = "success" | "warning" | "danger" | "error" | "neutral" | "info" | "pending";

export function StatusBadge({
  tone,
  children,
}: {
  tone: StatusTone;
  children: string;
}) {
  return <span className={`status-badge status-${tone}`}>{children}</span>;
}
