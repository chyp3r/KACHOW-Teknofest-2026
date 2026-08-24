import {
  ArrowUpRight,
  BarChart3,
  CheckCircle2,
  Clock3,
  FileCheck2,
  FilePenLine,
  FileSearch,
  FileText,
  Inbox,
  MessageSquare,
  Route,
  Sparkles,
  Upload,
} from "lucide-react";
import { Link } from "react-router-dom";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { StatusBadge } from "../components/StatusBadge";
import {
  DocumentStatusChart,
  TypeDistribution,
  WeeklyActivityChart,
  type ActivityPoint,
  type DistributionItem,
} from "../features/home/HomeDashboardCharts";
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
  const readyDrafts = drafts.drafts.filter(
    (item) =>
      !item.requires_human_approval &&
      !item.missing_information?.length &&
      (item.confidence_score ?? 0) >= 80,
  ).length;
  const pendingWork = pendingDocuments + reviewDocuments + drafts.inboxTotal + conversations.unreadTotal;
  const localActivity = buildActivity(documents, drafts.drafts.map((item) => item.updated_at));
  const activity = localActivity;
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
    ? analytics.units.slice(0, 4).map((item, index) => ({ label: item.destination ?? "Belirtilmemiş", value: item.count, tone: tones[index] }))
    : localDistribution;
  const metrics = canViewAnalytics && analytics.summary ? [
    { label: "Toplam evrak", value: analytics.summary.document_count, note: "Şirket genelindeki kayıtlar", icon: FileText, tone: "blue", route: "/documents" },
    { label: "Taslaklar", value: analytics.summary.draft_stats.total, note: `${analytics.summary.draft_stats.requires_human_approval} insan onayı bekliyor`, icon: FilePenLine, tone: "violet", route: "/drafts" },
    { label: "Aktif kullanıcı", value: analytics.summary.active_users_7d, note: "Son 7 günlük çalışma", icon: FileCheck2, tone: "emerald", route: "/admin" },
    { label: "Engellenen işlem", value: analytics.summary.guardrail_blocked_total, note: "Guardrail kararları", icon: Inbox, tone: "amber", route: "/admin" },
  ] : [
    { label: "Toplam evrak", value: documents.length, note: `${readyDocuments} işleme hazır`, icon: FileText, tone: "blue", route: "/documents" },
    { label: "Tamamlanan analiz", value: readyDocuments, note: `${reviewDocuments} inceleme bekliyor`, icon: FileCheck2, tone: "emerald", route: "/documents" },
    { label: "Taslaklar", value: drafts.total, note: `${readyDrafts} gönderime hazır`, icon: FilePenLine, tone: "violet", route: "/drafts" },
    { label: "Bekleyen işler", value: pendingWork, note: `${conversations.unreadTotal} okunmamış mesaj`, icon: Inbox, tone: "amber", route: "/messages" },
  ];

  return (
    <div className="page page-scroll home-page">
      <ApiErrorNotice error={drafts.errorObject ?? conversations.errorObject} />
      <section className="home-hero">
        <div className="home-hero-copy">
          <span><Sparkles /> KACHOW çalışma alanı</span>
          <h1>Ana Sayfa</h1>
          <p>
            Hoş geldiniz, <strong>{user?.username ?? "kullanıcı"}</strong>. Evrak,
            taslak ve karar süreçlerinizin güncel görünümü burada.
          </p>
          <small>{DATE_FORMAT.format(new Date())}</small>
        </div>
        <div className="home-hero-actions">
          <Link className="button button-primary control-md" to="/chats">
            <MessageSquare />Yeni sohbet
          </Link>
          <Link className="button home-hero-secondary control-md" to="/documents">
            <Upload />Evrakları aç
          </Link>
        </div>
        <div className="home-hero-orbit" aria-hidden="true">
          <span><FileSearch /></span><i /><b />
        </div>
      </section>

      <section className="home-quick-section">
        <header><div><h2>Hızlı işlemler</h2><p>Sık kullanılan çalışma adımlarına doğrudan geçin.</p></div></header>
        <div className="home-quick-grid">
          <Link className="is-blue" to="/documents">
            <FileSearch /><span><strong>Evrak analiz et</strong><small>Yeni evrak ekleyin ve inceleyin.</small></span><ArrowUpRight />
          </Link>
          <Link className="is-violet" to="/drafts">
            <FilePenLine /><span><strong>Taslak hazırla</strong><small>Resmî yazışma sürecini başlatın.</small></span><ArrowUpRight />
          </Link>
          <Link className="is-emerald" to="/drafts">
            <Route /><span><strong>Birim yönlendirme</strong><small>Hedef birim önerilerini inceleyin.</small></span><ArrowUpRight />
          </Link>
          <Link className="is-amber" to="/messages">
            <MessageSquare /><span><strong>Mesajları görüntüle</strong><small>Ekip iletişimini takip edin.</small></span><ArrowUpRight />
          </Link>
        </div>
      </section>

      <section className="home-metric-grid" aria-label="Genel istatistikler">
        {metrics.map(({ label, value, note, icon: Icon, tone, route }) => (
          <Link key={label} to={route} className={`home-metric-card is-${tone}`}>
            <span><Icon /></span>
            <div>
              <small>{label}</small>
              <strong>{loading || drafts.loading || (canViewAnalytics && analytics.loading) ? "—" : value}</strong>
              <p>{note}</p>
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
            <StatusBadge tone="info">Son 7 gün</StatusBadge>
          </header>
          <WeeklyActivityChart points={activity} />
        </section>
        <section className="home-panel home-status-panel">
          <header>
            <div>
              <span className="home-panel-icon is-emerald"><CheckCircle2 /></span>
              <div><h2>Evrak durumu</h2><p>Karar sürecine hazırlık</p></div>
            </div>
          </header>
          <DocumentStatusChart
            ready={readyDocuments}
            review={reviewDocuments}
            pending={pendingDocuments}
          />
          <p className="home-status-note">Bekliyor → analiz edilmedi · İncelenecek → eksik veya uyumsuz alan var · Hazır → kontroller tamamlandı</p>
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
              <div><h2>{canViewAnalytics ? "Birim hareketliliği" : "Evrak dağılımı"}</h2><p>{canViewAnalytics ? "Yönlendirilen taslak hacmi" : "Belge türlerine göre yoğunluk"}</p></div>
            </div>
          </header>
          {distribution.length ? (
            <TypeDistribution items={distribution} />
          ) : (
            <p className="home-panel-empty">Dağılım için evrak ekleyin.</p>
          )}
        </section>
      </div>

    </div>
  );
}
