import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RootUserInsights } from "../../types/management";
import { PlatformUserInsights } from "./PlatformUserInsights";

const DATA: RootUserInsights = {
  kpis: {
    total_users: 10,
    active_7d: 3,
    active_30d: 6,
    activity_rate_30d: 0.6,
    new_7d: 1,
    new_30d: 4,
    total_runs: 240,
    runs_per_active_user_30d: 40,
  },
  daily_activity: [
    { date: "2026-08-25", active_users: 2, runs: 10 },
    { date: "2026-08-26", active_users: 3, runs: 18 },
  ],
  by_role: { employee: 7, admin: 2, root: 1 },
  seats_by_company: [
    { company_id: "c1", name: "Kurum A", user_count: 7, is_active: true },
    { company_id: "c2", name: "Kurum B", user_count: 3, is_active: false },
  ],
  top_users: [
    {
      user_id: "u1",
      username: "employee",
      role: "employee",
      company_id: "c1",
      company_name: "Kurum A",
      run_count: 84,
      draft_count: 28,
      document_count: 13,
      session_count: 33,
      last_seen: new Date().toISOString(),
    },
  ],
  runs_by_intent: { draft: 56, assist: 70 },
  runs_by_status: { completed: 40, failed: 5 },
  guardrail_by_decision: { passed: 19, redacted: 7 },
  token_usage: {
    by_agent: { WriterAgent: 1200 },
    by_kind: { completion: 1200 },
    total: 1200,
    available: true,
  },
};

describe("PlatformUserInsights", () => {
  it("shows a spinner while loading", () => {
    render(<PlatformUserInsights data={undefined} loading />);
    expect(screen.getByText("Kullanıcı istatistikleri yükleniyor…")).toBeInTheDocument();
  });

  it("renders KPIs, Turkish labels, the top-users table and the token panel", () => {
    render(<PlatformUserInsights data={DATA} loading={false} />);

    expect(screen.getByText("Toplam kullanıcı")).toBeInTheDocument();
    expect(screen.getByText("%60")).toBeInTheDocument(); // activity_rate_30d

    // Turkish role / intent / status / guardrail / agent labels
    for (const label of ["Çalışan", "Taslak", "Tamamlandı", "Maskelendi", "Yazar"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }

    const table = screen.getByRole("table");
    expect(within(table).getByText("employee")).toBeInTheDocument();
    expect(within(table).getByText("Kurum A")).toBeInTheDocument();
  });

  it("shows an empty state for the token panel when Prometheus is unavailable", () => {
    render(
      <PlatformUserInsights
        data={{ ...DATA, token_usage: { by_agent: {}, by_kind: {}, total: 0, available: false } }}
        loading={false}
      />,
    );
    expect(screen.getByText(/Prometheus'a ulaşılamadı/)).toBeInTheDocument();
  });
});
