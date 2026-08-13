import type { ReactNode } from "react";

export function SectionHeader({ title, description, action, className = "" }: { title: ReactNode; description?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <header className={`section-header ${className}`.trim()}>
      <div><h2>{title}</h2>{description && <p>{description}</p>}</div>
      {action && <div className="section-actions">{action}</div>}
    </header>
  );
}
