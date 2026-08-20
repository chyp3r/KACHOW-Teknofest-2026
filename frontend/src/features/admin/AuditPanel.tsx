import { CheckCircle2, Search, ShieldCheck, ShieldX } from "lucide-react";
import { useState } from "react";
import { Button } from "../../components/Button";
import { Input } from "../../components/FormControls";
import { StatusBadge } from "../../components/StatusBadge";
import { Alert, Card, Spinner } from "../../components/Surface";
import { useAudit } from "../../hooks/useAudit";

export function AuditPanel({ companyId }: { companyId?: string }) {
  const [query, setQuery] = useState("");
  const audit = useAudit(companyId);
  const filtered = audit.entries.filter((item) => `${item.action} ${item.resource_type ?? ""} ${item.resource_id ?? ""} ${item.actor_user_id ?? ""}`.toLocaleLowerCase("tr-TR").includes(query.toLocaleLowerCase("tr-TR")));
  return <div className="admin-section">
    {audit.error && <Alert variant="error">{audit.error instanceof Error ? audit.error.message : "Denetim kayıtları yüklenemedi."}</Alert>}
    {audit.verification && <Alert variant={audit.verification.valid ? "success" : "error"} icon={audit.verification.valid ? <ShieldCheck /> : <ShieldX />} title={audit.verification.valid ? "Denetim zinciri doğrulandı" : "Denetim zinciri bozuk"}>{audit.verification.rows_checked} kayıt kontrol edildi.{audit.verification.reason ? ` ${audit.verification.reason}` : ""}</Alert>}
    <Card className="management-panel"><header className="management-panel-header"><div><h2>Denetim kayıtları</h2><p>{audit.total} kayıt · en yeni işlemler önce</p></div><Button variant="outline" leadingIcon={<CheckCircle2 />} loading={audit.verifying} onClick={() => void audit.verify()}>Zinciri doğrula</Button></header><div className="management-toolbar"><Input leadingIcon={<Search />} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="İşlem, kullanıcı veya kaynak ara…" aria-label="Denetim kayıtlarında ara" /></div>{audit.loading ? <div className="table-loading"><Spinner />Kayıtlar yükleniyor…</div> : <ul className="management-list audit-list">{filtered.map((entry) => <li key={entry.id}><time>{new Date(entry.created_at).toLocaleString("tr-TR")}</time><div><strong>{entry.action}</strong><small>{entry.actor_role ?? "sistem"} · {entry.actor_user_id ?? "sistem"}</small><p>{entry.resource_type ?? "kaynak"}{entry.resource_id ? ` · ${entry.resource_id}` : ""}</p></div><StatusBadge tone={entry.decision === "permit" ? "success" : entry.decision === "deny" ? "danger" : "neutral"}>{entry.decision}</StatusBadge></li>)}</ul>}</Card>
  </div>;
}
