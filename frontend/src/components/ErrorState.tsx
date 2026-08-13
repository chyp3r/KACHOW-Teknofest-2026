import { AlertCircle, RotateCcw } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "./Button";
import { EmptyState } from "./EmptyState";

export function ErrorState({
  title,
  description,
  onRetry,
  technicalDetails,
  correlationId,
  compact = false,
}: {
  title: string;
  description: string;
  onRetry?: () => void;
  technicalDetails?: ReactNode;
  correlationId?: string;
  compact?: boolean;
}) {
  const details = technicalDetails || correlationId ? (
    <details className="error-state-details">
      <summary>Teknik ayrıntılar</summary>
      {technicalDetails}
      {correlationId && <p>İstek kimliği: <code>{correlationId}</code></p>}
    </details>
  ) : undefined;
  return (
    <div className="error-state">
      <EmptyState
        compact={compact}
        icon={AlertCircle}
        title={title}
        description={description}
        primaryAction={onRetry ? <Button variant="secondary" leadingIcon={<RotateCcw />} onClick={onRetry}>Tekrar dene</Button> : undefined}
        secondaryAction={details}
      />
    </div>
  );
}
