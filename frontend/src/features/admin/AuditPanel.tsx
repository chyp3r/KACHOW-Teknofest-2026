import { CheckCircle2, Search, ShieldCheck, ShieldX } from "lucide-react";
import { useState } from "react";
import { Button } from "../../components/Button";
import { Input } from "../../components/FormControls";
import { StatusBadge } from "../../components/StatusBadge";
import { Alert, Card, Spinner } from "../../components/Surface";
import { useAudit } from "../../hooks/useAudit";

const ACTION_LABELS: Record<string, string> = { create: "Oluşturma", update: "Güncelleme", delete: "Silme", read: "Görüntüleme", login: "Oturum açma", export: "Dışa aktarma", share: "Paylaşma", verify: "Doğrulama" };
const RESOURCE_LABELS: Record<string, string> = { document: "Evrak", draft: "Taslak", user: "Kullanıcı", company: "Kurum", unit: "Birim", chat: "Sohbet", audit: "Denetim kaydı" };
const DECISION_LABELS: Record<string, string> = { permit: "İzin verildi", allow: "İzin verildi", deny: "Reddedildi", block: "Engellendi" };

function readable(value: string | null, labels: Record<string, string>, fallback: string) {
  if (!value) return fallback;
  const normalized = value.toLocaleLowerCase("tr-TR");
  return labels[normalized] ?? value.replace(/[._-]+/g, " ").replace(/(^|\s)\S/g, (letter) => letter.toLocaleUpperCase("tr-TR"));
}

export function AuditPanel({ companyId }: { companyId?: string }) {
  const [query, setQuery] = useState("");
  const audit = useAudit(companyId);
  const filtered = audit.entries.filter((item) => `${item.action} ${item.resource_type ?? ""} ${item.resource_id ?? ""} ${item.actor_user_id ?? ""}`.toLocaleLowerCase("tr-TR").includes(query.toLocaleLowerCase("tr-TR")));
  const permitted = audit.entries.filter((item) => ["permit", "allow"].includes(item.decision.toLowerCase())).length;
  const denied = audit.entries.filter((item) => ["deny", "block"].includes(item.decision.toLowerCase())).length;
  return <div className="admin-section">
    {audit.error && <Alert variant="error">{audit.error instanceof Error ? audit.error.message : "Denetim kayıtları yüklenemedi."}</Alert>}
    {audit.verification && <Alert variant={audit.verification.valid ? "success" : "error"} icon={audit.verification.valid ? <ShieldCheck /> : <ShieldX />} title={audit.verification.valid ? "Denetim zinciri doğrulandı" : "Denetim zinciri bozuk"}>{audit.verification.rows_checked} kayıt kontrol edildi.{audit.verification.reason ? ` ${audit.verification.reason}` : ""}</Alert>}
    <div className="admin-overview-grid audit-overview"><Card className="admin-metric-card"><span><CheckCircle2 /></span><div><small>İzin verilen</small><strong>{permitted}</strong></div></Card><Card className="admin-metric-card"><span><ShieldX /></span><div><small>Reddedilen / engellenen</small><strong>{denied}</strong></div></Card><Card className="admin-metric-card"><span><Search /></span><div><small>Gösterilen kayıt</small><strong>{filtered.length}</strong></div></Card></div>
    <Card className="management-panel"><header className="management-panel-header"><div><h2>Denetim kayıtları</h2><p>{audit.total} kayıt · en yeni işlemler önce</p></div><Button variant="outline" leadingIcon={<CheckCircle2 />} loading={audit.verifying} onClick={() => void audit.verify()}>Zinciri doğrula</Button></header><div className="management-toolbar"><Input leadingIcon={<Search />} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="İşlem, kullanıcı veya kaynak ara…" aria-label="Denetim kayıtlarında ara" /></div>{audit.loading ? <div className="table-loading"><Spinner />Kayıtlar yükleniyor…</div> : <ul className="management-list audit-list">{filtered.map((entry) => <li key={entry.id}><time>{new Date(entry.created_at).toLocaleString("tr-TR")}</time><div><strong>{readable(entry.action, ACTION_LABELS, "Sistem işlemi")}</strong><small>{readable(entry.actor_role, {}, "Sistem")} · {entry.actor_user_id ?? "Otomatik işlem"}</small><p>{readable(entry.resource_type, RESOURCE_LABELS, "Genel kaynak")}{entry.resource_id ? ` · ${entry.resource_id}` : ""}{entry.reason ? ` · ${entry.reason}` : ""}</p></div><StatusBadge tone={["permit", "allow"].includes(entry.decision) ? "success" : ["deny", "block"].includes(entry.decision) ? "danger" : "neutral"}>{readable(entry.decision, DECISION_LABELS, "Kaydedildi")}</StatusBadge></li>)}</ul>}</Card>
  </div>;
}
