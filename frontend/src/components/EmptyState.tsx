import type { LucideIcon } from "lucide-react";

export function EmptyState({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <Icon size={24} />
      </span>
      <h2>{title}</h2>
      <p>{description}</p>
    </div>
  );
}
