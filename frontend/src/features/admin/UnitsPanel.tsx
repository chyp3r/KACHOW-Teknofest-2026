import { Building2, Pencil, Plus, Trash2, UserPlus, Users, X } from "lucide-react";
import { useState } from "react";
import { Button, IconButton } from "../../components/Button";
import { ConfirmationDialog } from "../../components/ConfirmationDialog";
import { Input, Select, Textarea } from "../../components/FormControls";
import { Drawer } from "../../components/Overlay";
import { Alert, Card, Spinner } from "../../components/Surface";
import { useAdminUsers } from "../../hooks/useAdminUsers";
import { useUnitManagement } from "../../hooks/useUnitManagement";
import type { Unit } from "../../types/units";

export function UnitsPanel({ canManage }: { canManage: boolean }) {
  const [selected, setSelected] = useState<Unit | null>(null);
  const [editing, setEditing] = useState<Unit | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [memberId, setMemberId] = useState("");
  const [memberRole, setMemberRole] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Unit | null>(null);
  const management = useUnitManagement(selected?.id);
  const users = useAdminUsers(true);
  const openForm = (unit?: Unit) => { setEditing(unit ?? null); setName(unit?.name ?? ""); setDescription(unit?.description ?? ""); setCreating(true); };
  const save = async () => { if (!name.trim() || !description.trim()) return; if (editing) await management.update({ id: editing.id, changes: { name, description } }); else await management.create({ name, description }); setCreating(false); };
  return <div className="admin-section">
    {management.error && <Alert variant="error">{management.error instanceof Error ? management.error.message : "Birim işlemi tamamlanamadı."}</Alert>}
    <Card className="management-panel">
      <header className="management-panel-header"><div><h2>Birimler</h2><p>{management.units.length} birim · yönlendirme ve üyelik yapısı</p></div>{canManage && <Button leadingIcon={<Plus />} onClick={() => openForm()}>Yeni birim</Button>}</header>
      {creating && <div className="management-form"><Input label="Birim adı" value={name} maxLength={200} onChange={(event) => setName(event.target.value)} /><Textarea label="Görev ve kapsam" rows={3} maxLength={2000} value={description} onChange={(event) => setDescription(event.target.value)} /><div><Button variant="ghost" onClick={() => setCreating(false)}>Vazgeç</Button><Button loading={management.busy} onClick={() => void save()}>Kaydet</Button></div></div>}
      {management.loading ? <div className="table-loading"><Spinner />Birimler yükleniyor…</div> : <ul className="management-list management-unit-list">{management.units.map((unit) => <li key={unit.id}><button type="button" className="management-list-main" onClick={() => setSelected(unit)}><span className="management-icon"><Building2 /></span><span><strong>{unit.name}</strong><small>{unit.description}</small></span></button><span className={`management-state ${unit.is_active ? "is-active" : ""}`}>{unit.is_active ? "Aktif" : "Pasif"}</span>{canManage && <div className="management-row-actions"><IconButton size="sm" icon={<Pencil />} aria-label="Birimi düzenle" onClick={() => openForm(unit)} /><IconButton size="sm" icon={<Trash2 />} aria-label="Birimi sil" onClick={() => setDeleteTarget(unit)} /></div>}</li>)}</ul>}
    </Card>
    <Drawer open={Boolean(selected)} title={selected?.name ?? "Birim"} onClose={() => setSelected(null)} className="management-drawer" bodyClassName="management-drawer-body">
      {selected && <div className="management-stack"><p>{selected.description}</p><header className="management-section-header"><div><h3><Users /> Üyeler</h3><p>{management.members.length} kullanıcı</p></div></header>{canManage && <div className="management-inline-form"><Select label="Kullanıcı" value={memberId} onChange={(event) => setMemberId(event.target.value)}><option value="">Kullanıcı seçin</option>{users.users.filter((user) => !management.members.some((member) => member.user_id === user.id)).map((user) => <option key={user.id} value={user.id}>{user.username} — {user.email}</option>)}</Select><Input label="Birim içi rol" value={memberRole} placeholder="Örn. lead" onChange={(event) => setMemberRole(event.target.value)} /><Button leadingIcon={<UserPlus />} disabled={!memberId} loading={management.busy} onClick={() => void management.addMember({ unitId: selected.id, userId: memberId, isPrimary: false, roleInUnit: memberRole }).then(() => { setMemberId(""); setMemberRole(""); })}>Üye ekle</Button></div>}{management.membersLoading ? <Spinner /> : <ul className="management-list">{management.members.map((member) => <li key={member.user_id}><div><strong>{member.username}</strong><small>{member.email} · {member.role_in_unit || "Üye"}{member.is_primary ? " · Birincil" : ""}</small></div>{canManage && <IconButton size="sm" icon={<X />} aria-label="Üyeyi çıkar" onClick={() => void management.removeMember({ unitId: selected.id, userId: member.user_id })} />}</li>)}</ul>}</div>}
    </Drawer>
    <ConfirmationDialog open={Boolean(deleteTarget)} title="Birimi sil" description={`${deleteTarget?.name ?? "Bu birim"} kalıcı olarak silinecek.`} confirmLabel="Sil" busy={management.busy} onCancel={() => setDeleteTarget(null)} onConfirm={() => deleteTarget && void management.remove(deleteTarget.id).then(() => setDeleteTarget(null))} />
  </div>;
}
