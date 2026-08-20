import { Send } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "../../components/Button";
import { Textarea } from "../../components/FormControls";
import { Dialog } from "../../components/Overlay";
import { PersonPickerBody } from "../messaging/PersonPickerBody";
import { queryKeys } from "../../query/queryKeys";
import { transferService } from "../../services/transferService";
import { unitsService } from "../../services/unitsService";

export function DraftSendDialog({
  open,
  title,
  draftId,
  destination,
  sending,
  onClose,
  onSend,
}: {
  open: boolean;
  title: string;
  draftId: string;
  destination?: string | null;
  sending: boolean;
  onClose: () => void;
  onSend: (recipientIds: string[], message: string) => Promise<void>;
}) {
  const [recipientIds, setRecipientIds] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const recommendations = useQuery({ queryKey: queryKeys.transferRecommendations(draftId), queryFn: () => transferService.recommendations(draftId), enabled: open });
  const units = useQuery({ queryKey: queryKeys.units, queryFn: unitsService.list, enabled: open && Boolean(destination) });
  const suggestedUnit = units.data?.find((unit) => unit.name === destination);
  const suggestedRecipients = useQuery({ queryKey: ["units", suggestedUnit?.id ?? "", "suggested-recipients"], queryFn: () => unitsService.suggestedRecipients(suggestedUnit!.id), enabled: open && Boolean(suggestedUnit) });
  const suggestions = recommendations.data?.length ? recommendations.data.map((item) => ({ id: item.user_id, name: item.username, detail: item.source === "favorite_in_unit" ? `${item.unit_name} · Favori` : item.unit_name })) : (suggestedRecipients.data ?? []).map((item) => ({ id: item.user_id, name: item.username, detail: item.role_in_unit || destination || "Önerilen alıcı" }));

  const close = () => {
    if (sending) return;
    setRecipientIds([]);
    setMessage("");
    setError(null);
    onClose();
  };

  const send = async () => {
    setError(null);
    try {
      await onSend(recipientIds, message);
      close();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Taslak gönderilemedi.");
    }
  };

  return (
    <Dialog open={open} title="Taslağı gönder" description={title} onClose={close}>
      <div className="draft-send-dialog">
        {suggestions.length > 0 && <section className="recipient-suggestions"><h3>Önerilen alıcılar</h3><div>{suggestions.map((item) => <Button key={item.id} size="sm" variant={recipientIds.includes(item.id) ? "primary" : "outline"} onClick={() => setRecipientIds((current) => current.includes(item.id) ? current.filter((id) => id !== item.id) : [...current, item.id])}>{item.name}<small>{item.detail}</small></Button>)}</div></section>}
        <PersonPickerBody
          mode="select"
          selectedUserIds={recipientIds}
          onToggleSelect={(userId) => setRecipientIds((current) => current.includes(userId) ? current.filter((id) => id !== userId) : [...current, userId])}
        />
        <Textarea label="İletim notu" rows={2} maxLength={2000} value={message} onChange={(event) => setMessage(event.target.value)} placeholder="İsteğe bağlı kısa bir not ekleyin." />
        {error && <p className="draft-send-error">{error}</p>}
        <div className="draft-send-actions">
          <Button variant="ghost" disabled={sending} onClick={close}>Vazgeç</Button>
          <Button leadingIcon={<Send />} loading={sending} disabled={recipientIds.length === 0} onClick={() => void send()}>Seçilenlere gönder</Button>
        </div>
      </div>
    </Dialog>
  );
}
