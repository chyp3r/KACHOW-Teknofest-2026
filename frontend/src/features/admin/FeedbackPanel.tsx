import { useQuery } from "@tanstack/react-query";
import { MessageSquareText, ThumbsDown, ThumbsUp } from "lucide-react";
import { Card, Spinner } from "../../components/Surface";
import { queryKeys } from "../../query/queryKeys";
import { feedbackService } from "../../services/feedbackService";

const TARGET_LABELS: Record<string, string> = { draft: "Taslak", revision: "Revizyon", assist_reply: "Asistan cevabı", routing: "Yönlendirme" };

export function FeedbackPanel({ companyId }: { companyId: string }) {
  const entries = useQuery({ queryKey: queryKeys.feedbackAdmin(companyId), queryFn: () => feedbackService.list(1, 100) });
  const stats = useQuery({ queryKey: queryKeys.feedbackStats(companyId), queryFn: () => feedbackService.stats(companyId) });
  const data = stats.data;
  return <div className="management-stack">
    <div className="admin-overview-grid"><Card className="admin-metric-card"><span><MessageSquareText /></span><div><small>Toplam</small><strong>{data?.total ?? "—"}</strong></div></Card><Card className="admin-metric-card"><span><ThumbsUp /></span><div><small>Olumlu</small><strong>{data ? Math.round((data.likes / Math.max(1, data.total)) * 100) : "—"}%</strong></div></Card><Card className="admin-metric-card"><span><ThumbsDown /></span><div><small>Olumsuz</small><strong>{data?.dislikes ?? "—"}</strong></div></Card></div>
    <Card className="management-panel"><header className="management-panel-header"><div><h2>Geri bildirimler</h2><p>AI eğitim verisinin kaynak oyları.</p></div></header>{entries.isLoading ? <div className="table-loading"><Spinner />Geri bildirimler yükleniyor…</div> : <ul className="management-list">{entries.data?.items.map((entry) => <li key={entry.id}><span className={`management-feedback-icon is-${entry.signal}`}>{entry.signal === "like" ? <ThumbsUp /> : <ThumbsDown />}</span><div><strong>{TARGET_LABELS[entry.target_kind] ?? entry.target_kind}</strong><small>{new Date(entry.created_at).toLocaleString("tr-TR")}</small>{entry.comment && <p>{entry.comment}</p>}</div></li>)}</ul>}</Card>
  </div>;
}
