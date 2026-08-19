import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, Trash2, UserRound } from "lucide-react";
import { useState } from "react";
import { Button, IconButton } from "../../components/Button";
import { Select, Textarea } from "../../components/FormControls";
import { Drawer } from "../../components/Overlay";
import { Alert, Spinner } from "../../components/Surface";
import { queryKeys } from "../../query/queryKeys";
import { userService } from "../../services/userService";
import { ROLE_LABELS, type User } from "../../types/users";

const ACTIONS = [
  "document:read", "document:update", "document:delete", "draft:read", "draft:update",
  "draft:delete", "draft:send", "artifact:transfer", "unit:manage", "user:manage",
  "permission:grant", "permission:revoke",
];

const ACTION_LABELS: Record<string, string> = {
  "document:read": "Evrak görüntüleme", "document:update": "Evrak düzenleme", "document:delete": "Evrak silme",
  "draft:read": "Taslak görüntüleme", "draft:update": "Taslak düzenleme", "draft:delete": "Taslak silme",
  "draft:send": "Taslak gönderme", "artifact:transfer": "Evrak/taslak transferi", "unit:manage": "Birim yönetimi",
  "user:manage": "Kullanıcı yönetimi", "permission:grant": "İzin verme", "permission:revoke": "İzin kaldırma",
};

export function UserPermissionsDrawer({ user, open, canManage, onClose }: { user: User | null; open: boolean; canManage: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const [action, setAction] = useState(ACTIONS[0]);
  const [effect, setEffect] = useState<"permit" | "deny">("permit");
  const [scope, setScope] = useState<"self" | "any">("self");
  const [reason, setReason] = useState("");
  const detail = useQuery({ queryKey: queryKeys.userDetail(user?.id ?? ""), queryFn: () => userService.get(user!.id), enabled: open && Boolean(user) });
  const permissions = useQuery({ queryKey: queryKeys.userPermissions(user?.id ?? ""), queryFn: () => userService.permissions(user!.id), enabled: open && Boolean(user) });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.userPermissions(user!.id) });
  const grant = useMutation({
    mutationFn: () => userService.grantPermission(user!.id, {
      action, resource_type: action.split(":")[0], resource_selector: scope === "any" ? { any: true } : { owner: "self" }, effect, reason: reason || null,
    }),
    onSuccess: () => { refresh(); setFormOpen(false); setReason(""); },
  });
  const revoke = useMutation({ mutationFn: userService.revokePermission, onSuccess: refresh });
  const target = detail.data ?? user;
  return (
    <Drawer open={open} title="Kullanıcı ayrıntıları" onClose={onClose} className="management-drawer" bodyClassName="management-drawer-body">
      {!target ? null : (
        <div className="management-stack">
          <section className="management-identity"><span><UserRound /></span><div><h3>{target.username}</h3><p>{target.email}</p><small>{ROLE_LABELS[target.role]} · {target.clearance_level}</small></div></section>
          {(detail.isLoading || permissions.isLoading) && <div className="table-loading"><Spinner />Bilgiler yükleniyor…</div>}
          {(detail.error || permissions.error || grant.error || revoke.error) && <Alert variant="error">{String((detail.error ?? permissions.error ?? grant.error ?? revoke.error) instanceof Error ? (detail.error ?? permissions.error ?? grant.error ?? revoke.error as Error).message : "İşlem tamamlanamadı.")}</Alert>}
          <section>
            <header className="management-section-header"><div><h3><KeyRound /> Ek izinler</h3><p>Rol izinlerinin üzerine uygulanan açık yetki kayıtları.</p></div>{canManage && <Button size="sm" variant="outline" leadingIcon={<Plus />} onClick={() => setFormOpen((value) => !value)}>İzin ekle</Button>}</header>
            {formOpen && <div className="management-inline-form"><Select label="İşlem" value={action} onChange={(event) => setAction(event.target.value)}>{ACTIONS.map((item) => <option key={item} value={item}>{ACTION_LABELS[item]}</option>)}</Select><Select label="Karar" value={effect} onChange={(event) => setEffect(event.target.value as "permit" | "deny")}><option value="permit">İzin ver</option><option value="deny">Engelle</option></Select><Select label="Kapsam" value={scope} onChange={(event) => setScope(event.target.value as "self" | "any")}><option value="self">Kendi kaynakları</option><option value="any">Şirket genelinde</option></Select><Textarea label="Gerekçe" rows={2} maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} /><Button loading={grant.isPending} onClick={() => grant.mutate()}>Kaydet</Button></div>}
            {permissions.data?.length ? <ul className="management-list">{permissions.data.map((item) => <li key={item.id}><div><strong>{ACTION_LABELS[item.action] ?? item.action}</strong><small>{item.effect === "permit" ? "İzinli" : "Engelli"} · {"any" in item.resource_selector ? "Şirket geneli" : "Kendi kaynakları"}</small>{item.reason && <p>{item.reason}</p>}</div>{canManage && <IconButton size="sm" icon={<Trash2 />} aria-label="İzni kaldır" loading={revoke.isPending} onClick={() => revoke.mutate(item.id)} />}</li>)}</ul> : !permissions.isLoading && <p className="detail-empty">Tanımlanmış ek izin bulunmuyor.</p>}
          </section>
        </div>
      )}
    </Drawer>
  );
}
