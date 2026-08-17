import { AlertTriangle, Send } from "lucide-react";
import { Button } from "../../components/Button";
import { FormActions } from "../../components/LayoutPrimitives";
import { Alert } from "../../components/Surface";
import type { InterruptState } from "../../types/chat";

/**
 * Renders `artifact_transfer_disambiguate` (candidates unresolved -- human
 * picks, never the model) and `artifact_transfer_confirm` (a single
 * resolved proposal awaiting the actual send). Both branch off
 * `InterruptPanel` the same way `writing_brief`/`missing_information` do --
 * this is a paused workflow gate, not a chat message, and every field here
 * comes straight from the backend's interrupt payload (never model-
 * generated text), including the cross-unit warning: `payload.cross_unit`
 * is computed by `app.domains.transfers.policy.TransferPolicy` before this
 * card ever renders, so it can't be "forgotten" the way a generated
 * sentence could be.
 */
export function TransferConfirmCard({
  interrupt,
  loading,
  onSelect,
  onApprove,
  onReject,
}: {
  interrupt: InterruptState;
  loading: boolean;
  onSelect: (recipientId: string) => void;
  onApprove: () => void;
  onReject: () => void;
}) {
  const artifactLabel = interrupt.payload.artifact_kind === "document" ? "Evrak" : "Taslak";

  if (interrupt.kind === "artifact_transfer_disambiguate") {
    const candidates = interrupt.payload.candidates ?? [];
    return (
      <div className="transfer-confirm-card">
        <p className="transfer-confirm-question">
          {artifactLabel}ı göndermek istediğiniz kişiyi seçin:
        </p>
        <ul className="transfer-candidate-list">
          {candidates.map((candidate) => (
            <li key={candidate.user_id} className="transfer-candidate-row">
              <span className="transfer-candidate-info">
                <strong>{candidate.username}</strong>
                {candidate.unit_name && <small>{candidate.unit_name}</small>}
              </span>
              <Button size="sm" disabled={loading} onClick={() => onSelect(candidate.user_id)}>
                Seç
              </Button>
            </li>
          ))}
        </ul>
        <FormActions className="transfer-confirm-actions">
          <Button variant="destructive" disabled={loading} onClick={onReject}>
            Vazgeç
          </Button>
        </FormActions>
      </div>
    );
  }

  return (
    <div className="transfer-confirm-card">
      <p className="transfer-confirm-question">
        {artifactLabel}
        {typeof interrupt.payload.source_version === "number" ? ` (v${interrupt.payload.source_version})` : ""}{" "}
        gönderilsin mi?
      </p>
      {interrupt.payload.cross_unit && (
        <Alert variant="warning" icon={<AlertTriangle size={16} />}>
          Alıcı, bu {artifactLabel.toLowerCase()}ın yönlendirildiği birimden farklı bir birimde.
        </Alert>
      )}
      <FormActions className="transfer-confirm-actions">
        <Button leadingIcon={<Send size={14} />} disabled={loading} onClick={onApprove}>
          Onayla ve gönder
        </Button>
        <Button variant="destructive" disabled={loading} onClick={onReject}>
          Vazgeç
        </Button>
      </FormActions>
    </div>
  );
}
