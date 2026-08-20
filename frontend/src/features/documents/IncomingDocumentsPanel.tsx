import { Check, Copy, FileText, Inbox, Trash2 } from "lucide-react";
import { Button, IconButton } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Alert, Card, Spinner } from "../../components/Surface";
import { usePersonalPool } from "../../hooks/usePersonalPool";

export function IncomingDocumentsPanel() {
  const pool = usePersonalPool();
  return <Card className="management-panel pool-panel"><header className="management-panel-header"><div><h2><Inbox /> Gelen evraklar</h2><p>{pool.pool?.name ?? "Kişisel havuz"} · {pool.total} kayıt</p></div></header>{pool.error && <Alert variant="error">{pool.error instanceof Error ? pool.error.message : "Gelen evraklar yüklenemedi."}</Alert>}{pool.loading ? <div className="table-loading"><Spinner />Gelen evraklar yükleniyor…</div> : pool.items.length === 0 ? <EmptyState icon={Inbox} title="Gelen evrak yok" description="Size işlem için iletilen evraklar burada görünür." /> : <ul className="management-list pool-item-list">{pool.items.map((item) => <li key={item.id}><span className="management-icon"><FileText /></span><div><strong>{item.file_name ?? item.document_id}</strong><small>{item.source} · {new Date(item.created_at).toLocaleString("tr-TR")}</small>{item.note && <p>{item.note}</p>}</div><span className={`management-state ${item.acknowledged_at ? "is-active" : ""}`}>{item.acknowledged_at ? "Teslim alındı" : "Yeni"}</span><div className="management-row-actions">{!item.acknowledged_at && <Button size="sm" variant="outline" leadingIcon={<Check />} loading={pool.busy} onClick={() => void pool.acknowledge(item.id)}>Teslim aldım</Button>}<Button size="sm" variant="outline" leadingIcon={<Copy />} loading={pool.busy} onClick={() => void pool.adopt(item.id)}>Çalışma kopyası</Button><IconButton size="sm" icon={<Trash2 />} aria-label="Havuzdan kaldır" loading={pool.busy} onClick={() => void pool.remove(item.id)} /></div></li>)}</ul>}</Card>;
}
