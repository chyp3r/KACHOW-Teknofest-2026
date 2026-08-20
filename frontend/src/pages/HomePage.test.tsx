import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { DocumentMetadata } from "../types/documents";
import { HomePage } from "./HomePage";

vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: { username: "admin" } }) }));
vi.mock("../hooks/useCompanyAnalytics", () => ({ useCompanyAnalytics: () => ({ summary: undefined, documentTimeseries: [], draftTimeseries: [], units: [], loading: false, error: null }) }));
vi.mock("../hooks/useConversations", () => ({ useConversations: () => ({
  conversations: [], unreadTotal: 3, loading: false, error: null, errorObject: null,
}) }));
vi.mock("../hooks/useDrafts", () => ({ useDrafts: () => ({
  drafts: [
    { id: "draft-ready", updated_at: new Date().toISOString(), requires_human_approval: false, missing_information: [], confidence_score: 91 },
    { id: "draft-review", updated_at: new Date().toISOString(), requires_human_approval: true, missing_information: [], confidence_score: 72 },
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
  it("summarizes live workspace data with charts and quick actions", () => {
    render(<MemoryRouter><HomePage documents={documents} loading={false} /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Ana Sayfa" })).toBeInTheDocument();
    expect(screen.getByText(/Hoş geldiniz/)).toHaveTextContent("admin");
    const metrics = screen.getByRole("region", { name: "Genel istatistikler" });
    expect(within(metrics).getByRole("link", { name: /Toplam evrak 2/ })).toBeInTheDocument();
    expect(within(metrics).getByRole("link", { name: /Taslaklar 2/ })).toHaveTextContent("1 gönderime hazır");
    expect(within(metrics).getByRole("link", { name: /Bekleyen işler 5/ })).toHaveTextContent("3 okunmamış mesaj");
    expect(screen.getByRole("img", { name: "1 hazır, 0 inceleme gerekli, 1 analiz bekliyor" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Son yedi günlük evrak ve taslak hareketliliği" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Evrak analiz et/ })).toHaveAttribute("href", "/documents");
    expect(screen.getByRole("link", { name: /Taslak hazırla/ })).toHaveAttribute("href", "/drafts");
    expect(screen.getByRole("link", { name: /Birim yönlendirme/ })).toHaveAttribute("href", "/drafts");
  });

  it("keeps useful empty states when no records exist", () => {
    render(<MemoryRouter><HomePage documents={[]} loading={false} /></MemoryRouter>);

    expect(screen.getByText("Henüz evrak bulunmuyor.")).toBeInTheDocument();
    expect(screen.getByText("Dağılım için evrak ekleyin.")).toBeInTheDocument();
  });
});
