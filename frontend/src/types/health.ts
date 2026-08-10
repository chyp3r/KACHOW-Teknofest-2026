export type DependencyHealth = "ok" | "fail" | "disabled" | "unavailable";

export interface HealthStatus {
  status: "healthy" | "degraded" | string;
  project: string;
  environment: string;
  dependencies?: Record<"postgres" | "redis" | "qdrant" | "ollama", DependencyHealth>;
  checkpointer?: DependencyHealth;
  router_semantic?: DependencyHealth;
}
