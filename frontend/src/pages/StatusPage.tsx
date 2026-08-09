import { RefreshCw } from "lucide-react";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { ErrorState } from "../components/ErrorState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { useHealth } from "../hooks/useHealth";
import { Button } from "../components/Button";
import { Card, Spinner } from "../components/Surface";

const LABELS: Record<string, string> = {
  postgres: "PostgreSQL", redis: "Redis", qdrant: "Qdrant", ollama: "Ollama",
  checkpointer: "Checkpointer", router_semantic: "Semantik yönlendirici",
};

export function StatusPage() {
  const health = useHealth();
  const items = health.status ? {
    ...(health.status.dependencies ?? {}),
    ...(health.status.checkpointer ? { checkpointer: health.status.checkpointer } : {}),
    ...(health.status.router_semantic ? { router_semantic: health.status.router_semantic } : {}),
  } : {};
  return (
    <div className="page page-scroll">
      <PageHeader title="Sistem Durumu" description="Normal kontrol otomatik, bağımlılık kontrolleri yalnızca isteğinizle çalışır." secondaryActions={
        <Button variant="secondary" leadingIcon={<RefreshCw />} loading={health.deepLoading} onClick={() => void health.runDeep()}>Derin kontrol</Button>
      } />
      {health.status && <ApiErrorNotice error={health.errorObject ?? health.error} />}
      {health.loading ? <div className="centered-state"><Spinner label="Sistem durumu yükleniyor" />Sistem durumu yükleniyor…</div> : health.status ? (
        <Card className="health-panel" padding="default">
          <div className="section-heading"><div><h2>{health.status.project}</h2><p>{health.status.environment}</p></div><StatusBadge tone={health.status.status === "healthy" ? "success" : "warning"}>{health.status.status === "healthy" ? "Sağlıklı" : "Kısıtlı"}</StatusBadge></div>
          {Object.keys(items).length === 0 ? <p className="detail-empty">Bağımlılık ayrıntıları için derin kontrolü çalıştırın.</p> : (
            <ul className="health-grid">{Object.entries(items).map(([key, value]) => <li key={key}><span>{LABELS[key] ?? key}</span><StatusBadge tone={value === "ok" ? "success" : value === "fail" ? "danger" : "neutral"}>{value === "ok" ? "Çalışıyor" : value === "fail" ? "Başarısız" : value === "disabled" ? "Kapalı" : "Kullanılamıyor"}</StatusBadge></li>)}</ul>
          )}
        </Card>
      ) : <ErrorState title="Durum alınamadı" description="Sistem durumuna şu anda ulaşılamıyor." onRetry={() => void health.refresh()} technicalDetails={health.error ?? undefined} />}
    </div>
  );
}
