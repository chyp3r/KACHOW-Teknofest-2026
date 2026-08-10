import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  actions,
  primaryAction,
  secondaryActions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  primaryAction?: ReactNode;
  secondaryActions?: ReactNode;
}) {
  const renderedActions = actions ?? (primaryAction || secondaryActions ? (
    <>
      {secondaryActions && <div className="page-secondary-actions">{secondaryActions}</div>}
      {primaryAction && <div className="page-primary-action">{primaryAction}</div>}
    </>
  ) : null);
  return (
    <header className="page-header">
      <div className="page-header-copy">
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {renderedActions && <div className="page-actions">{renderedActions}</div>}
    </header>
  );
}
