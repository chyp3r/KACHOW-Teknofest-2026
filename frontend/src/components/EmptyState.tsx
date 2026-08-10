import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export function EmptyState({
  icon: Icon,
  title,
  description,
  primaryAction,
  secondaryAction,
  compact = false,
  className = "",
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  primaryAction?: ReactNode;
  secondaryAction?: ReactNode;
  compact?: boolean;
  className?: string;
}) {
  return (
    <div className={`empty-state ${compact ? "empty-state-compact" : ""} ${className}`.trim()}>
      <span className="empty-icon" aria-hidden="true">
        <Icon />
      </span>
      <h2>{title}</h2>
      <p>{description}</p>
      {(primaryAction || secondaryAction) && (
        <div className="empty-state-actions">{primaryAction}{secondaryAction}</div>
      )}
    </div>
  );
}
