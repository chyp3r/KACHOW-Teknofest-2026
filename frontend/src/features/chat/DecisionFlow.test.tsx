import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DecisionFlow } from "./DecisionFlow";

describe("DecisionFlow", () => {
  it("maps internal nodes to readable Turkish stages", () => {
    render(
      <DecisionFlow
        statuses={{ planning: "completed", classification: "running" }}
        results={{}}
        meta={{}}
        planSteps={["classification", "draft"]}
      />,
    );
    expect(screen.getAllByText("Yönlendirme").length).toBeGreaterThan(0);
    expect(
      screen.getByText("Uygunluk ve Mevzuat Kontrolü"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Tamamlandı").length).toBeGreaterThan(0);
    expect(screen.getAllByText("İşleniyor").length).toBeGreaterThan(0);
  });

  it("keeps raw workflow data collapsed under technical details", () => {
    render(
      <DecisionFlow
        statuses={{ planning: "completed" }}
        results={{ planning: { intent: "chat" } }}
        meta={{}}
        planSteps={["chat"]}
      />,
    );
    fireEvent.click(screen.getByText("Teknik Detaylar"));
    expect(screen.getByText(/"plan_steps"/)).toBeInTheDocument();
  });
});
