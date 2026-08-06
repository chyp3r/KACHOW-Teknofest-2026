export function StatusBadge({
  tone,
  children,
}: {
  tone: "success" | "warning" | "danger" | "neutral" | "info";
  children: string;
}) {
  return <span className={`status-badge status-${tone}`}>{children}</span>;
}
