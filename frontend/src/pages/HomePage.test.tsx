import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DocumentMetadata } from "../types/documents";
import { HomePage } from "./HomePage";

const state = vi.hoisted(() => ({
  units: [
    { destination: "Bilgi İşlem", unit_id: "unit-1", count: 5 },
    { destination: null, unit_id: null, count: 4 },
  ],
}));

vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: { username: "admin", role: "admin", company_id: "company-1" } }) }));
vi.mock("../hooks/useCompanyAnalytics", () => ({ useCompanyAnalytics: () => ({
  summary: {
    document_count: 8,
    draft_stats: { total: 15, avg_confidence_score: 82, requires_human_approval: 9 },
    run_status: {},
    active_users_7d: 2,
    guardrail_blocked_total: 0,
    usage: {},
  },
  documentTimeseries: [], draftTimeseries: [], units: state.units, loading: false, error: null,
}) }));
vi.mock("../hooks/useConversations", () => ({ useConversations: () => ({
  conversations: [], unreadTotal: 3, loading: false, error: null, errorObject: null,
}) }));
vi.mock("../hooks/useDrafts", () => ({ useDrafts: () => ({
  drafts: [
    { id: "draft-ready", updated_at: new Date().toISOString(), requires_human_approval: false, missing_information: [], confidence_score: 91 },
    { id: "draft-review", updated_at: new Date().toISOString(), requires_human_approval: true, missing_information: [], confidence_score: 72 },
    { id: "draft-pending", updated_at: new Date().toISOString(), requires_human_approval: false, missing_information: [], confidence_score: 42 },
  ],
  total: 2, inboxTotal: 1, loading: false, error: null, errorObject: null,
}) }));

const documents: DocumentMetadata[] = [
  {
    file_name: "hazir-evrak.pdf", storage_path: "documents/hazir-evrak.pdf",
    upload_time: new Date().toISOString(), document_type: "official_letter",
    document_type_label: "Resmî Yazı", compliance_status: "compliant", summary: "Hazır", analyzed: true,
  },
  {
    file_name: "bekleyen-evrak.pdf", storage_path: "documents/bekleyen-evrak.pdf",
    upload_time: new Date().toISOString(), document_type: "report",
    document_type_label: "Rapor", compliance_status: "", summary: "Bekliyor", analyzed: false,
  },
];

describe("HomePage", () => {
  beforeEach(() => {
    state.units = [
      { destination: "Bilgi İşlem", unit_id: "unit-1", count: 5 },
      { destination: null, unit_id: null, count: 4 },
    ];
  });

  it("summarizes live workspace data with charts and quick actions", () => {
    render(<MemoryRouter><HomePage documents={documents} loading={false} /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Ana Sayfa" })).toBeInTheDocument();
    expect(screen.getByText(/Hoş geldiniz/)).toHaveTextContent("admin");
    const metrics = screen.getByRole("region", { name: "Genel istatistikler" });
    expect(within(metrics).getByRole("link", { name: /8 Toplam evrak/ })).toBeInTheDocument();
    expect(within(metrics).getByRole("link", { name: /15 Taslaklar/ })).toBeInTheDocument();
    expect(within(metrics).getByRole("link", { name: /9 Onay bekleyen/ })).toBeInTheDocument();
    expect(within(metrics).getByRole("link", { name: /0 Engellenen işlem/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Taslak durumu" })).toBeInTheDocument();
    expect(screen.getByText("Gönderim ve inceleme hazırlığı")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "1 gönderime hazır, 1 inceleme gerekiyor, 1 hazırlanıyor" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Son yedi günlük evrak ve taslak hareketliliği" })).toBeInTheDocument();
    expect(screen.getByText("2 evrak · 3 taslak")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Taslakların hedef birim dağılımı" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Kısayollar" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Evrak analiz et/ })).toHaveAttribute("href", "/documents");
    expect(screen.getByRole("link", { name: /Taslak hazırla/ })).toHaveAttribute("href", "/drafts");
    expect(screen.getByRole("link", { name: /Birim yönlendirme/ })).toHaveAttribute("href", "/drafts");
  });

  it("keeps useful empty states when no records exist", () => {
    state.units = [];
    render(<MemoryRouter><HomePage documents={[]} loading={false} /></MemoryRouter>);

    expect(screen.getByText("Henüz evrak bulunmuyor.")).toBeInTheDocument();
    expect(screen.getByText("Dağılım için evrak ekleyin.")).toBeInTheDocument();
  });
});
