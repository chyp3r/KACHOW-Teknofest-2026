import { StatusBadge } from "../../components/StatusBadge";
import { Card, Spinner } from "../../components/Surface";
import type { DependencyHealth } from "../../types/health";
import type { RootHealth } from "../../types/management";

const DEP_LABELS: Record<string, string> = {
  postgres: "PostgreSQL",
  redis: "Redis",
  qdrant: "Qdrant",
  ollama: "Ollama",
  checkpointer: "Checkpointer",
  router_semantic: "Semantik yönlendirici",
};

function depTone(value: DependencyHealth): "success" | "danger" | "neutral" {
  return value === "ok" ? "success" : value === "fail" ? "danger" : "neutral";
}

function depLabel(value: DependencyHealth): string {
  if (value === "ok") return "Çalışıyor";
  if (value === "fail") return "Başarısız";
  if (value === "disabled") return "Kapalı";
  return "Kullanılamıyor";
}

/** The "Sistem Sağlığı" tab of the Platform Yönetimi page. */
export function PlatformHealthInsights({
  data,
  loading,
  companyNames,
  checkedAt,
}: {
  data: RootHealth | undefined;
  loading: boolean;
  companyNames: Record<string, string>;
  checkedAt?: number;
}) {
  if (loading) {
    return (
      <div className="table-loading">
        <Spinner />
        Sistem sağlığı yükleniyor…
      </div>
    );
  }

  const dependencies: Record<string, DependencyHealth> = data
    ? {
        ...(data.dependencies ?? {}),
        ...(data.checkpointer ? { checkpointer: data.checkpointer } : {}),
        ...(data.router_semantic ? { router_semantic: data.router_semantic } : {}),
      }
    : {};

  return (
    <div className="admin-section">
      <Card className="management-panel">
        <header className="management-panel-header">
          <div>
            <h2>Platform sağlığı</h2>
            <p>Bağımlılık kontrolleri ve son kontrol zamanı</p>
          </div>
          <StatusBadge tone={data?.status === "healthy" ? "success" : "warning"}>
            {data?.status === "healthy" ? "Sağlıklı" : (data?.status ?? "Yükleniyor")}
          </StatusBadge>
        </header>
        {Object.keys(dependencies).length > 0 ? (
          <ul className="health-grid">
            {Object.entries(dependencies).map(([key, value]) => (
              <li key={key}>
                <span>{DEP_LABELS[key] ?? key}</span>
                <StatusBadge tone={depTone(value)}>{depLabel(value)}</StatusBadge>
              </li>
            ))}
          </ul>
        ) : (
          <p className="detail-empty">Bağımlılık ayrıntısı bulunmuyor.</p>
        )}
        {checkedAt ? (
          <p className="detail-empty">
            Son kontrol: {new Date(checkedAt).toLocaleString("tr-TR")}
          </p>
        ) : null}
      </Card>

      <Card className="management-panel">
        <header className="management-panel-header">
          <div>
            <h2>Kurumların son aktivitesi</h2>
            <p>Kurum başına en son kaydedilen işlem zamanı</p>
          </div>
        </header>
        <ul className="management-list">
          {Object.entries(data?.companies_last_activity ?? {}).map(([companyId, lastSeen]) => (
            <li key={companyId}>
              <div>
                <strong>{companyNames[companyId] ?? companyId}</strong>
                <small>
                  {lastSeen ? new Date(lastSeen).toLocaleString("tr-TR") : "Aktivite yok"}
                </small>
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
