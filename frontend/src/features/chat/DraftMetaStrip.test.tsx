import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DraftMetaStrip } from "./DraftMetaStrip";

describe("DraftMetaStrip", () => {
  it("renders nothing without a draft", () => {
    const { container } = render(<DraftMetaStrip details={{}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows score, routed unit, and a ready badge for a clean completed draft", () => {
    render(
      <DraftMetaStrip
        details={{
          draft: { draft: "Taslak metni", status: "COMPLETED", combined_score: 92 },
          routing: { routed_unit: "İnsan Kaynakları" },
        }}
      />,
    );
    expect(screen.getByText("Güven skoru: 92/100")).toBeInTheDocument();
    expect(screen.getByText(/Önerilen birim: İnsan Kaynakları/)).toBeInTheDocument();
    expect(screen.getByText("Hazır")).toBeInTheDocument();
  });

  it("shows neutral review notes alongside the ready badge -- never an approval prompt", () => {
    render(
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
    expect(screen.getByText("Kontrol notları")).toBeInTheDocument();
    expect(screen.getByText("Eksik yapısal unsurlar: Kapanış ifadesi.")).toBeInTheDocument();
    expect(screen.queryByText(/İnsan onayı/)).not.toBeInTheDocument();
    // The draft still shipped -- there is no blocking approval gate, so the
    // ready badge shows alongside the review notes, not instead of them.
    expect(screen.getByText("Hazır")).toBeInTheDocument();
  });

  it("shows the alternative unit alongside the primary suggestion", () => {
    render(
      <DraftMetaStrip
        details={{
          draft: { draft: "Taslak metni", status: "COMPLETED", combined_score: 92 },
          routing: { routed_unit: "Mali İşler", alternative_units: ["Destek Hizmetleri"] },
        }}
      />,
    );
    expect(
      screen.getByText(/Önerilen birim: Mali İşler · Alternatif: Destek Hizmetleri/),
    ).toBeInTheDocument();
  });

  it("shows the applied-rules score breakdown when present", () => {
    render(
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

    expect(screen.getByText("Skor dökümü (2)")).toBeInTheDocument();
    expect(screen.getByText(/Eksik Konu satırı — -8 puan/)).toBeInTheDocument();
    expect(screen.getByText(/Kaynakta doğrulanamayan iddia \(×3\) — -30 puan/)).toBeInTheDocument();
  });

  it("renders no breakdown when applied_rules is absent", () => {
    render(
      <DraftMetaStrip
        details={{
          draft: { draft: "Taslak metni", status: "COMPLETED", combined_score: 100 },
        }}
      />,
    );

    expect(screen.queryByText(/Skor dökümü/)).not.toBeInTheDocument();
  });

  it("shows the rejection reason for a rejected draft", () => {
    render(
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
});
