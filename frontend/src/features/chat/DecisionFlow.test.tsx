import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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
    expect(screen.getByText("Evrak analizi")).toBeInTheDocument();
    expect(screen.getByText("Taslak oluşturma")).toBeInTheDocument();
    expect(screen.getByText("İnsan onayı")).toBeInTheDocument();
    expect(screen.getByText("Çalışıyor")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Evrak analizi.*Çalışıyor/ })).toHaveAttribute(
      "aria-current",
      "step",
    );
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
    expect(screen.queryByRole("img", { name: "Karar akışı düğüm grafiği" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Teknik grafiği görüntüle"));
    expect(screen.getByRole("img", { name: "Karar akışı düğüm grafiği" })).toBeVisible();
    expect(screen.getByText("Teknik grafiği gizle")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Teknik detaylar"));
    expect(screen.getByText(/"plan_steps"/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Teknik grafiği gizle"));
    expect(screen.queryByRole("img", { name: "Karar akışı düğüm grafiği" })).not.toBeInTheDocument();
    expect(screen.getByText("Teknik grafiği görüntüle")).toBeInTheDocument();
  });

  it("supports zooming, panning, keyboard movement, and resetting the technical graph", () => {
    render(
      <DecisionFlow
        statuses={{ planning: "completed" }}
        results={{}}
        meta={{}}
        planSteps={["classification"]}
      />,
    );
    fireEvent.click(screen.getByText("Teknik grafiği görüntüle"));

    const viewport = screen.getByRole("region", { name: "Etkileşimli teknik grafik" });
    const graph = screen.getByTestId("interactive-graph-svg");
    expect(graph.querySelector("circle")).toHaveAttribute("r", "36");
    vi.spyOn(graph, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      top: 0,
      right: 560,
      bottom: 650,
      left: 0,
      width: 560,
      height: 650,
      toJSON: () => ({}),
    });
    const initialViewBox = graph.getAttribute("viewBox");
    fireEvent.click(screen.getByRole("button", { name: "Grafiği büyüt" }));
    expect(screen.getByLabelText("Yakınlaştırma %120")).toBeInTheDocument();
    const zoomedViewBox = graph.getAttribute("viewBox");
    expect(zoomedViewBox).not.toBe(initialViewBox);
    expect(graph.style.transform).toBe("");

    fireEvent(viewport, new MouseEvent("pointerdown", { bubbles: true, clientX: 10, clientY: 12 }));
    fireEvent(viewport, new MouseEvent("pointermove", { bubbles: true, clientX: 34, clientY: 42 }));
    fireEvent(viewport, new MouseEvent("pointerup", { bubbles: true, clientX: 34, clientY: 42 }));
    const pannedViewBox = graph.getAttribute("viewBox");
    expect(pannedViewBox).not.toBe(zoomedViewBox);

    viewport.focus();
    fireEvent.keyDown(viewport, { key: "ArrowRight" });
    expect(graph.getAttribute("viewBox")).not.toBe(pannedViewBox);

    fireEvent.click(screen.getByRole("button", { name: "Grafik görünümünü sıfırla" }));
    expect(graph.getAttribute("viewBox")).toBe(initialViewBox);
  });
});
