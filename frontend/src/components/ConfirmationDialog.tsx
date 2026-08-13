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
    <Dialog open={open} role="alertdialog" title={title} description={description} onClose={onCancel} footer={<>
          <Button variant="secondary" onClick={onCancel}>Vazgeç</Button>
          <Button variant="destructive" loading={busy} onClick={onConfirm}>{busy ? "İşleniyor…" : confirmLabel}</Button>
        </>}>
        <span className="dialog-icon" aria-hidden="true">
          <AlertTriangle />
        </span>
    </Dialog>
  );
}
