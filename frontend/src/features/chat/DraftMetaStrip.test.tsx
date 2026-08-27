import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DraftMetaStrip } from "./DraftMetaStrip";

vi.mock("../../services/unitsService", () => ({
  unitsService: {
    list: vi.fn().mockResolvedValue([
      { id: "unit-1", name: "Mali İşler", description: "Bütçe ve ödemeler.", is_active: true },
      { id: "unit-2", name: "İnsan Kaynakları", description: "Personel işleri.", is_active: true },
    ]),
  },
}));

const updateDestinationMock = vi.fn();
const getDraftMock = vi.fn();
const exportDraftMock = vi.fn();
vi.mock("../../services/draftService", () => ({
  draftService: {
    get: (draftId: string) => getDraftMock(draftId),
    updateDestination: (draftId: string, destination: string) =>
      updateDestinationMock(draftId, destination),
    export: (draftId: string, format: "docx" | "pdf", version?: number) =>
      exportDraftMock(draftId, format, version),
  },
}));

function renderWithQueryClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function expandDraftMeta() {
  fireEvent.click(screen.getByRole("button", { name: "Taslak kontrol ayrıntılarını göster" }));
}

describe("DraftMetaStrip", () => {
  beforeEach(() => {
    updateDestinationMock.mockReset();
    exportDraftMock.mockReset().mockResolvedValue(undefined);
    getDraftMock.mockReset().mockResolvedValue({
      id: "draft-1",
      destination: "İnsan Kaynakları",
      version: 3,
    });
  });

  it("renders nothing without a draft", () => {
    const { container } = renderWithQueryClient(<DraftMetaStrip details={{}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("starts compact with only the score and ready state, then reveals details", () => {
    renderWithQueryClient(
      <DraftMetaStrip
        details={{
          draft: { draft: "Taslak metni", status: "COMPLETED", combined_score: 92 },
          routing: { routed_unit: "İnsan Kaynakları" },
        }}
      />,
    );
    expect(screen.getByText("Güven skoru: 92/100")).toBeInTheDocument();
    expect(screen.getByText("Hazır")).toBeInTheDocument();
    expect(screen.queryByText(/Önerilen birim: İnsan Kaynakları/)).not.toBeInTheDocument();

    expandDraftMeta();

    expect(screen.getByText(/Önerilen birim: İnsan Kaynakları/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Taslak kontrol ayrıntılarını gizle" })).toHaveAttribute("aria-expanded", "true");
  });

  it("shows neutral review notes alongside the ready badge -- never an approval prompt", () => {
    renderWithQueryClient(
      <DraftMetaStrip
        details={{
          draft: {
            draft: "Taslak metni",
            status: "NEEDS_HUMAN_APPROVAL",
            combined_score: 40,
            requires_human_approval: true,
            evaluation_notes: "Eksik yapısal unsurlar: Kapanış ifadesi.",
          },
        }}
      />,
    );
    expect(screen.queryByText("Kontrol notları")).not.toBeInTheDocument();
    expandDraftMeta();
    expect(screen.getByText("Kontrol notları")).toBeInTheDocument();
    expect(screen.getByText("Eksik yapısal unsurlar: Kapanış ifadesi.")).toBeInTheDocument();
    expect(screen.queryByText(/İnsan onayı/)).not.toBeInTheDocument();
    // The draft still shipped -- there is no blocking approval gate, so the
    // ready badge shows alongside the review notes, not instead of them.
    expect(screen.getByText("Hazır")).toBeInTheDocument();
  });

  it("shows the alternative unit alongside the primary suggestion", () => {
    renderWithQueryClient(
      <DraftMetaStrip
        details={{
          draft: { draft: "Taslak metni", status: "COMPLETED", combined_score: 92 },
          routing: { routed_unit: "Mali İşler", alternative_units: ["Destek Hizmetleri"] },
        }}
      />,
    );
    expandDraftMeta();
    expect(
      screen.getByText(/Önerilen birim: Mali İşler · Alternatif: Destek Hizmetleri/),
    ).toBeInTheDocument();
  });

  it("shows the applied-rules score breakdown when present", () => {
    renderWithQueryClient(
      <DraftMetaStrip
        details={{
          draft: {
            draft: "Taslak metni",
            status: "NEEDS_HUMAN_APPROVAL",
            combined_score: 62,
            requires_human_approval: true,
            applied_rules: [
              {
                rule_id: "eksik_konu_satiri",
                label: "Eksik Konu satırı",
                occurrences: 1,
                penalty_applied: 8,
                forces_approval: true,
              },
              {
                rule_id: "dayanaksiz_iddia",
                label: "Kaynakta doğrulanamayan iddia",
                occurrences: 3,
                penalty_applied: 30,
                forces_approval: true,
              },
            ],
          },
        }}
      />,
    );

    expect(screen.queryByText("Skor dökümü (2)")).not.toBeInTheDocument();
    expandDraftMeta();
    expect(screen.getByText("Skor dökümü (2)")).toBeInTheDocument();
    expect(screen.getByText(/Eksik Konu satırı — -8 puan/)).toBeInTheDocument();
    expect(screen.getByText(/Kaynakta doğrulanamayan iddia \(×3\) — -30 puan/)).toBeInTheDocument();
  });

  it("renders no breakdown when applied_rules is absent", () => {
    renderWithQueryClient(
      <DraftMetaStrip
        details={{
          draft: { draft: "Taslak metni", status: "COMPLETED", combined_score: 100 },
        }}
      />,
    );

    expect(screen.queryByText(/Skor dökümü/)).not.toBeInTheDocument();
  });

  it("shows the rejection reason for a rejected draft", () => {
    renderWithQueryClient(
      <DraftMetaStrip
        details={{
          draft: {
            draft: "Taslak metni",
            status: "REJECTED",
            rejection_reason: "Üslup çok resmi değil.",
          },
        }}
      />,
    );
    expect(screen.getByText(/Reddedildi \(gerekçe: Üslup çok resmi değil.\)/)).toBeInTheDocument();
  });

  // ==========================================
  // UnitPicker wiring -- the bug this closes: routing always proposes a
  // unit now, but nothing in the live chat view let a user override it --
  // the picker only ever existed on the separate /drafts management page.
  // ==========================================
  it("renders the unit picker toggle when the message carries a persisted draft id", () => {
    renderWithQueryClient(
      <DraftMetaStrip
        details={{
          draft: { id: "draft-1", draft: "Taslak metni", status: "COMPLETED", combined_score: 92 },
          routing: { routed_unit: "İnsan Kaynakları" },
        }}
      />,
    );
    expandDraftMeta();
    expect(screen.getByRole("button", { name: "Birimi değiştir" })).toBeInTheDocument();
  });

  it("does not render the unit picker when the draft has no persisted id", () => {
    renderWithQueryClient(
      <DraftMetaStrip
        details={{
          draft: { draft: "Taslak metni", status: "COMPLETED", combined_score: 92 },
          routing: { routed_unit: "İnsan Kaynakları" },
        }}
      />,
    );
    expandDraftMeta();
    expect(screen.queryByRole("button", { name: "Birimi değiştir" })).not.toBeInTheDocument();
  });

  it("asks for a format from the compact download action", async () => {
    renderWithQueryClient(
      <DraftMetaStrip
        details={{
          draft: { id: "draft-1", draft: "Taslak metni", status: "COMPLETED", combined_score: 92 },
        }}
      />,
    );

    const formatMenu = screen.getByRole("menu", { name: "İndirme formatı" });
    const downloadDetails = formatMenu.closest("details");
    expect(downloadDetails).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("İndir"));
    expect(downloadDetails).toHaveAttribute("open");

    fireEvent.click(screen.getByRole("menuitem", { name: "Word (.docx)" }));

    await waitFor(() =>
      expect(exportDraftMock.mock.calls[0]?.slice(0, 2)).toEqual(["draft-1", "docx"]),
    );
    expect(downloadDetails).not.toHaveAttribute("open");
  });

  it("saves a picked unit and updates the displayed suggestion in place", async () => {
    updateDestinationMock.mockResolvedValueOnce({
      id: "draft-1",
      destination: "Mali İşler",
    });
    renderWithQueryClient(
      <DraftMetaStrip
        details={{
          draft: { id: "draft-1", draft: "Taslak metni", status: "COMPLETED", combined_score: 92 },
          routing: { routed_unit: "İnsan Kaynakları", alternative_units: ["Mali İşler"] },
        }}
      />,
    );

    expandDraftMeta();
    fireEvent.click(screen.getByRole("button", { name: "Birimi değiştir" }));
    const select = await screen.findByLabelText("Hedef birim");
    fireEvent.click(select);
    fireEvent.click(await screen.findByRole("option", { name: "Mali İşler" }));
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));

    await waitFor(() => expect(updateDestinationMock).toHaveBeenCalledWith("draft-1", "Mali İşler"));
    await waitFor(() =>
      expect(screen.getByText(/Hedef birim: Mali İşler/)).toBeInTheDocument(),
    );
  });

  it("rehydrates the persisted target unit instead of reverting to the old chat suggestion", async () => {
    getDraftMock.mockResolvedValueOnce({
      id: "draft-1",
      destination: "Mali İşler",
    });
    renderWithQueryClient(
      <DraftMetaStrip
        details={{
          draft: { id: "draft-1", draft: "Taslak metni", status: "COMPLETED", combined_score: 92 },
          routing: { routed_unit: "İnsan Kaynakları", alternative_units: ["Mali İşler"] },
        }}
      />,
    );

    expandDraftMeta();
    await waitFor(() =>
      expect(screen.getByText("Hedef birim: Mali İşler")).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Alternatif:/)).not.toBeInTheDocument();
  });
});
