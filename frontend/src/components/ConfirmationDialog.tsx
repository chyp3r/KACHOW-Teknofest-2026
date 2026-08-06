import { AlertTriangle } from "lucide-react";

export function ConfirmationDialog({
  open,
  title,
  description,
  confirmLabel,
  busy,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onCancel}>
      <div
        className="dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <span className="dialog-icon">
          <AlertTriangle size={20} />
        </span>
        <h2 id="dialog-title">{title}</h2>
        <p>{description}</p>
        <div className="dialog-actions">
          <button className="button button-secondary" onClick={onCancel}>
            Vazgeç
          </button>
          <button
            className="button button-danger"
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? "İşleniyor…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
