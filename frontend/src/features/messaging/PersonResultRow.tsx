import { Star } from "lucide-react";
import type { ReactNode } from "react";
import { IconButton } from "../../components/Button";
import { ROLE_LABELS } from "../../types/users";
import type { UserRole } from "../../types/users";

// A plain div, not `ListRow` -- this row needs its own nested favorite-star
// and action buttons, and `ListRow` itself renders as a `<button>` (nesting
// a `<button>` inside a `<button>` is invalid HTML and unreachable by
// keyboard). Same "cell with its own stopPropagation" shape
// `DraftTable.tsx`'s row actions already use for the same reason.
export function PersonResultRow({
  username,
  email,
  role,
  unitName,
  isFavorite,
  onToggleFavorite,
  action,
}: {
  username: string;
  email: string;
  role?: UserRole;
  unitName?: string | null;
  isFavorite?: boolean;
  onToggleFavorite?: () => void;
  action?: ReactNode;
}) {
  return (
    <div className="person-row" role="listitem">
      <span className="person-avatar" aria-hidden="true">
        {username.slice(0, 2).toLocaleUpperCase("tr-TR")}
      </span>
      <span className="person-row-content">
        <strong>{username}</strong>
        <span className="person-row-meta">
          {email}
          {role && <span className="person-role-chip">{ROLE_LABELS[role]}</span>}
          {unitName && <span className="person-unit-chip">{unitName}</span>}
        </span>
      </span>
      <span className="person-row-actions">
        {onToggleFavorite && (
          <IconButton
            icon={<Star fill={isFavorite ? "currentColor" : "none"} />}
            variant="ghost"
            className={isFavorite ? "is-active person-favorite-toggle" : "person-favorite-toggle"}
            aria-label={isFavorite ? "Favorilerden çıkar" : "Favorilere ekle"}
            aria-pressed={Boolean(isFavorite)}
            onClick={onToggleFavorite}
          />
        )}
        {action}
      </span>
    </div>
  );
}
