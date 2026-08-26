import {
  ArrowUpRight,
  BarChart3,
  Clock3,
  FileCheck2,
  FilePenLine,
  FileSearch,
  FileText,
  Inbox,
  MessageSquare,
  Route,
  Upload,
} from "lucide-react";
import { Link } from "react-router-dom";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { StatusBadge } from "../components/StatusBadge";
import {
  DraftStatusChart,
  TypeDistribution,
  WeeklyActivityChart,
  type ActivityPoint,
  type DistributionItem,
} from "../features/home/HomeDashboardCharts";
import { draftState } from "../features/drafts/draftState";
import { useAuth } from "../hooks/useAuth";
import { useConversations } from "../hooks/useConversations";
import { useDrafts } from "../hooks/useDrafts";
import { useCompanyAnalytics } from "../hooks/useCompanyAnalytics";
import type { DocumentMetadata } from "../types/documents";

const DAY_FORMAT = new Intl.DateTimeFormat("tr-TR", { weekday: "short" });
const DATE_FORMAT = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", year: "numeric" });

function dayKey(value: Date) {
  return `${value.getFullYear()}-${value.getMonth()}-${value.getDate()}`;
}

function buildActivity(documents: DocumentMetadata[], draftDates: string[]): ActivityPoint[] {
  const today = new Date();
  return Array.from({ length: 7 }, (_, offset) => {
    const date = new Date(today);
    date.setDate(today.getDate() - (6 - offset));
    const key = dayKey(date);
    return {
      label: DAY_FORMAT.format(date).replace(".", ""),
      documents: documents.filter((item) => dayKey(new Date(item.upload_time)) === key).length,
      drafts: draftDates.filter((value) => dayKey(new Date(value)) === key).length,
    };
  });
}

export function HomePage({
  documents,
  loading,
}: {
  documents: DocumentMetadata[];
  loading: boolean;
}) {
  const { user } = useAuth();
  const canViewAnalytics = user?.role === "admin" || user?.role === "manager";
  const analytics = useCompanyAnalytics(user?.company_id ?? undefined, 7, canViewAnalytics);
  const drafts = useDrafts(undefined, true);
  const conversations = useConversations();
  const isReady = (item: DocumentMetadata) =>
    item.analyzed !== false &&
    item.compliance_status.toLocaleLowerCase("tr-TR") === "compliant";
  const readyDocuments = documents.filter(isReady).length;
  const pendingDocuments = documents.filter((item) => item.analyzed === false).length;
  const reviewDocuments = Math.max(
    0,
    documents.length - readyDocuments - pendingDocuments,
  );
  const approvalDrafts = canViewAnalytics && analytics.summary
    ? analytics.summary.draft_stats.requires_human_approval
    : drafts.drafts.filter((item) => item.requires_human_approval).length;
  const draftStatusCounts = drafts.drafts.reduce(
    (counts, item) => {
      counts[draftState(item).category] += 1;
      return counts;
    },
    { ready: 0, review: 0, pending: 0 },
  );
  const pendingWork = pendingDocuments + reviewDocuments + drafts.inboxTotal + conversations.unreadTotal;
  const localActivity = buildActivity(documents, drafts.drafts.map((item) => item.updated_at));
  const activity = localActivity;
  const weeklyDocumentTotal = activity.reduce((total, item) => total + item.documents, 0);
  const weeklyDraftTotal = activity.reduce((total, item) => total + item.drafts, 0);
  const attentionCount = approvalDrafts + pendingDocuments + reviewDocuments;
  const recentDocuments = [...documents]
    .sort(
      (left, right) =>
        new Date(right.upload_time).getTime() - new Date(left.upload_time).getTime(),
    )
    .slice(0, 4);
  const typeCounts = documents.reduce<Record<string, number>>((counts, item) => {
    const label = item.document_type_label || item.document_type || "Diğer";
    counts[label] = (counts[label] ?? 0) + 1;
    return counts;
  }, {});
  const tones: DistributionItem["tone"][] = ["blue", "violet", "emerald", "amber"];
  const localDistribution = Object.entries(typeCounts)
    .sort(([, left], [, right]) => right - left)
    .slice(0, 4)
    .map(([label, value], index) => ({ label, value, tone: tones[index] }));
  const distribution = canViewAnalytics && analytics.units.length
    ? [...analytics.units]
      .sort((left, right) => Number(Boolean(left.destination)) - Number(Boolean(right.destination)) || right.count - left.count)
      .slice(0, 4)
      .map((item, index) => ({
        label: item.destination ?? "Belirtilmemiş",
        value: item.count,
        tone: (item.destination ? tones[index % 3] : "amber") as DistributionItem["tone"],
      }))
    : localDistribution;
  const metrics = canViewAnalytics && analytics.summary ? [
    { label: "Toplam evrak", value: analytics.summary.document_count, icon: FileText, tone: "blue", route: "/documents" },
    { label: "Taslaklar", value: analytics.summary.draft_stats.total, icon: FilePenLine, tone: "violet", route: "/drafts" },
    { label: "Onay bekleyen", value: approvalDrafts, icon: FileCheck2, tone: "emerald", route: "/drafts" },
    { label: "Engellenen işlem", value: analytics.summary.guardrail_blocked_total, icon: Inbox, tone: "amber", route: "/admin" },
  ] : [
    { label: "Toplam evrak", value: documents.length, icon: FileText, tone: "blue", route: "/documents" },
    { label: "Taslaklar", value: drafts.total, icon: FilePenLine, tone: "violet", route: "/drafts" },
    { label: "Onay bekleyen", value: approvalDrafts, icon: FileCheck2, tone: "emerald", route: "/drafts" },
    { label: "Bekleyen işler", value: pendingWork, icon: Inbox, tone: "amber", route: "/messages" },
  ];

  return (
    <div className="page page-scroll home-page">
      <ApiErrorNotice error={drafts.errorObject ?? conversations.errorObject} />
      <section className="home-hero">
        <div className="home-hero-copy">
          <h1>Ana Sayfa</h1>
          <p>
            Hoş geldiniz, <strong>{user?.username ?? "kullanıcı"}</strong>.
            {attentionCount > 0
              ? ` Dikkatinizi bekleyen ${attentionCount} işlem var.`
              : " Bekleyen kritik işleminiz bulunmuyor."}
          </p>
          <small>{DATE_FORMAT.format(new Date())}</small>
        </div>
        <div className="home-hero-actions">
          <Link className="button button-primary control-md" to="/chats">
            <MessageSquare />Yeni sohbet
          </Link>
          <Link className="button home-hero-secondary control-md" to="/documents">
            <Upload />Evrak yükle
          </Link>
        </div>
        <div className="home-hero-orbit" aria-hidden="true">
          <span><FileSearch /></span><i /><b />
        </div>
      </section>

      <section className="home-metric-grid" aria-label="Genel istatistikler">
        {metrics.map(({ label, value, icon: Icon, tone, route }) => (
          <Link key={label} to={route} className={`home-metric-card is-${tone}`}>
            <span><Icon /></span>
            <div>
              <strong>{loading || drafts.loading || (canViewAnalytics && analytics.loading) ? "—" : value}</strong>
              <small>{label}</small>
            </div>
            <ArrowUpRight />
          </Link>
        ))}
      </section>

      <div className="home-dashboard-grid">
        <section className="home-panel home-activity-panel">
          <header>
            <div>
              <span className="home-panel-icon is-blue"><BarChart3 /></span>
              <div><h2>Haftalık hareketlilik</h2><p>Evrak ve taslak üretim ritmi</p></div>
            </div>
            <StatusBadge tone="info">{`${weeklyDocumentTotal} evrak · ${weeklyDraftTotal} taslak`}</StatusBadge>
          </header>
          <WeeklyActivityChart points={activity} />
        </section>
        <section className="home-panel home-status-panel">
          <header>
            <div>
              <span className="home-panel-icon is-violet"><FilePenLine /></span>
              <div><h2>Taslak durumu</h2><p>Gönderim ve inceleme hazırlığı</p></div>
            </div>
          </header>
          <DraftStatusChart
            ready={draftStatusCounts.ready}
            review={draftStatusCounts.review}
            pending={draftStatusCounts.pending}
          />
        </section>

        <section className="home-panel home-recent-panel">
          <header>
            <div>
              <span className="home-panel-icon is-violet"><Clock3 /></span>
              <div><h2>Son evraklar</h2><p>En son eklenen kayıtlar</p></div>
            </div>
            <Link to="/documents">Tümünü gör <ArrowUpRight /></Link>
          </header>
          {recentDocuments.length ? (
            <ul>
              {recentDocuments.map((item) => (
                <li key={item.storage_path}>
                  <Link to={`/documents/${encodeURIComponent(item.storage_path)}`}>
                    <span className="home-file-icon"><FileText /></span>
                    <span>
                      <strong>{item.file_name}</strong>
                      <small>{item.document_type_label || item.document_type || "Belge"}</small>
                    </span>
                    <StatusBadge
                      tone={item.analyzed === false ? "pending" : isReady(item) ? "success" : "warning"}
                    >
                      {item.analyzed === false ? "Bekliyor" : isReady(item) ? "Hazır" : "İncelenecek"}
                    </StatusBadge>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="home-panel-empty">Henüz evrak bulunmuyor.</p>
          )}
        </section>
        <section className="home-panel home-types-panel">
          <header>
            <div>
              <span className="home-panel-icon is-amber"><BarChart3 /></span>
              <div><h2>{canViewAnalytics ? "Taslakların hedef birim dağılımı" : "Evrak dağılımı"}</h2><p>{canViewAnalytics ? "Yönlendirilen taslakların hedefleri" : "Belge türlerine göre yoğunluk"}</p></div>
            </div>
          </header>
          {distribution.length ? (
            <TypeDistribution items={distribution} />
          ) : (
            <p className="home-panel-empty">Dağılım için evrak ekleyin.</p>
          )}
        </section>
      </div>

      <section className="home-quick-section">
        <header><div><h2>Kısayollar</h2><p>Sık kullanılan çalışma adımları</p></div></header>
        <div className="home-quick-grid">
          <Link className="is-blue" to="/documents">
            <FileSearch /><span><strong>Evrak analiz et</strong></span><ArrowUpRight />
          </Link>
          <Link className="is-violet" to="/drafts">
            <FilePenLine /><span><strong>Taslak hazırla</strong></span><ArrowUpRight />
          </Link>
          <Link className="is-emerald" to="/drafts">
            <Route /><span><strong>Birim yönlendirme</strong></span><ArrowUpRight />
          </Link>
          <Link className="is-amber" to="/messages">
            <MessageSquare /><span><strong>Mesajları görüntüle</strong></span><ArrowUpRight />
          </Link>
        </div>
      </section>

    </div>
  );
}
