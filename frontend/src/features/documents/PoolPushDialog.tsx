import { useMutation, useQuery } from "@tanstack/react-query";
import { Send, Users } from "lucide-react";
import { useState } from "react";
import { Button } from "../../components/Button";
import { Select, Textarea } from "../../components/FormControls";
import { Dialog } from "../../components/Overlay";
import { Alert } from "../../components/Surface";
import { queryKeys } from "../../query/queryKeys";
import { poolService } from "../../services/poolService";
import { unitsService } from "../../services/unitsService";
import { PersonPickerBody } from "../messaging/PersonPickerBody";

export function PoolPushDialog({ open, documentId, onClose }: { open: boolean; documentId: string; onClose: () => void }) {
  const [mode, setMode] = useState<"people" | "unit">("people");
  const [recipientIds, setRecipientIds] = useState<string[]>([]);
  const [unitId, setUnitId] = useState("");
  const [note, setNote] = useState("");
  const units = useQuery({ queryKey: queryKeys.units, queryFn: unitsService.list, enabled: open });
  const personalPool = useQuery({ queryKey: queryKeys.personalPool, queryFn: poolService.mine, enabled: open });
  const push = useMutation({ mutationFn: () => poolService.push({ document_id: documentId, recipient_ids: mode === "people" ? recipientIds : undefined, unit_id: mode === "unit" ? unitId : undefined, note: note || undefined }), onSuccess: onClose });
  const addOwn = useMutation({ mutationFn: () => poolService.add(personalPool.data!.id, documentId, note || undefined), onSuccess: onClose });
  return <Dialog open={open} title="Evrakı havuza gönder" description={documentId} onClose={onClose}><div className="management-stack"><div className="new-conversation-tabs"><Button size="sm" variant={mode === "people" ? "primary" : "outline"} onClick={() => setMode("people")}>Kişiler</Button><Button size="sm" variant={mode === "unit" ? "primary" : "outline"} leadingIcon={<Users />} onClick={() => setMode("unit")}>Birim</Button></div>{mode === "people" ? <PersonPickerBody mode="select" selectedUserIds={recipientIds} onToggleSelect={(id) => setRecipientIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])} /> : <Select label="Birim" value={unitId} onChange={(event) => setUnitId(event.target.value)}><option value="">Birim seçin</option>{units.data?.filter((unit) => unit.is_active).map((unit) => <option key={unit.id} value={unit.id}>{unit.name}</option>)}</Select>}<Textarea label="İletim notu" rows={2} maxLength={1000} value={note} onChange={(event) => setNote(event.target.value)} />{(push.error || addOwn.error) && <Alert variant="error">{(push.error ?? addOwn.error) instanceof Error ? (push.error ?? addOwn.error as Error).message : "Evrak gönderilemedi."}</Alert>}<div className="management-form-actions"><Button variant="outline" loading={addOwn.isPending} disabled={!personalPool.data} onClick={() => addOwn.mutate()}>Kendi havuzuma ekle</Button><Button leadingIcon={<Send />} loading={push.isPending} disabled={mode === "people" ? recipientIds.length === 0 : !unitId} onClick={() => push.mutate()}>Havuza gönder</Button></div></div></Dialog>;
}
