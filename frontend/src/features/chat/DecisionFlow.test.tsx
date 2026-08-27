import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DecisionFlow } from "./DecisionFlow";

describe("DecisionFlow", () => {
  it("renders only the stages this turn actually planned, not a fixed 5-stage list", () => {
    render(
      <DecisionFlow
        statuses={{ planning: "completed", classification: "running" }}
        results={{}}
        meta={{}}
        planSteps={["classification"]}
        nodeOrder={["planning", "classification"]}
      />,
    );
    const stepper = screen.getByRole("list", { name: "İş akışı adımları" });
    expect(within(stepper).getAllByRole("button")).toHaveLength(2);
    expect(within(stepper).getByText("Evrak Analizi")).toBeInTheDocument();
    expect(within(stepper).queryByText("Taslak")).not.toBeInTheDocument();
    expect(within(stepper).queryByText("İnsan Onayı")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Evrak Analizi.*Çalışıyor/ })).toHaveAttribute(
      "aria-current",
      "step",
    );
  });

  it("groups source excerpts and verification nodes under the draft stage instead of giving them their own row", () => {
    render(
      <DecisionFlow
        statuses={{ planning: "completed", draft: "completed", source_chunks: "completed", verify: "completed", judge: "completed" }}
        results={{}}
        meta={{}}
        planSteps={["draft"]}
        nodeOrder={["planning", "draft", "source_chunks", "verify", "judge"]}
      />,
    );
    const stepper = screen.getByRole("list", { name: "İş akışı adımları" });
    expect(within(stepper).getAllByRole("button")).toHaveLength(2);
    expect(within(stepper).getByText("Taslak Hazırlama")).toBeInTheDocument();
    expect(within(stepper).getByText("Kaynak Alıntılar")).toBeInTheDocument();
    expect(within(stepper).getByText("Doğrulama")).toBeInTheDocument();
    expect(within(stepper).getByText("Kalite Yargıcı")).toBeInTheDocument();
  });

  it("renders an assist turn's tool calls as sub-items of the assist stage, with a Turkish label", () => {
    render(
      <DecisionFlow
        statuses={{ planning: "completed", assist: "running" }}
        results={{}}
        meta={{}}
        planSteps={["assist"]}
        nodeOrder={["planning", "assist"]}
        toolCalls={[{ node: "assist", tool: "suggest_unit", args: {} }]}
      />,
    );
    const stepper = screen.getByRole("list", { name: "İş akışı adımları" });
    expect(within(stepper).getByText("Asistan")).toBeInTheDocument();
    expect(within(stepper).getByText("Birim önerisi")).toBeInTheDocument();
    expect(within(stepper).queryByText("suggest_unit")).not.toBeInTheDocument();
  });

  it("never drops a node the backend announces even when it isn't in the known registry", () => {
    render(
      <DecisionFlow
        statuses={{ totally_new_node: "running" }}
        results={{}}
        meta={{}}
        planSteps={[]}
        nodeOrder={["totally_new_node"]}
        nodeLabels={{ totally_new_node: "Yeni Adım" }}
      />,
    );
    expect(screen.getByText("Yeni Adım")).toBeInTheDocument();
  });

  it("prefers the backend-supplied label over the frontend fallback", () => {
    render(
      <DecisionFlow
        statuses={{ classification: "running" }}
        results={{}}
        meta={{}}
        planSteps={["classification"]}
        nodeOrder={["classification"]}
        nodeLabels={{ classification: "Belge Taraması" }}
      />,
    );
    const stepper = screen.getByRole("list", { name: "İş akışı adımları" });
    expect(within(stepper).getByText("Belge Taraması")).toBeInTheDocument();
    expect(within(stepper).queryByText("Evrak Analizi")).not.toBeInTheDocument();
  });

  it("keeps raw workflow data collapsed under technical details", () => {
    render(
      <DecisionFlow
        statuses={{ planning: "completed" }}
        results={{ planning: { intent: "assist" } }}
        meta={{}}
        planSteps={["assist"]}
        planIntent="assist"
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
