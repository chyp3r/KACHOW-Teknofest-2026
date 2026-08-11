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

  it("shows the approval note instead of the ready badge when approval is required", () => {
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
    expect(
      screen.getByText(/İnsan onayı gerekiyor: Eksik yapısal unsurlar/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Hazır")).not.toBeInTheDocument();
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
