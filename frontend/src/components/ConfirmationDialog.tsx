import { AlertTriangle } from "lucide-react";
import { Button } from "./Button";
import { Dialog } from "./Overlay";

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
  return (
    <Dialog
      open={open}
      role="alertdialog"
      title={title}
      onClose={onCancel}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>
            Vazgeç
          </Button>
          <Button variant="destructive" loading={busy} onClick={onConfirm}>
            {busy ? "İşleniyor…" : confirmLabel}
          </Button>
        </>
      }
    >
      <div className="confirmation-dialog-body">
        <span className="confirmation-dialog-icon" aria-hidden="true">
          <AlertTriangle />
        </span>
        <p>{description}</p>
      </div>
    </Dialog>
  );
}
