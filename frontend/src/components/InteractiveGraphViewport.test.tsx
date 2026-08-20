import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { InteractiveGraphViewport } from "./InteractiveGraphViewport";
import { useGraphViewport } from "./graphViewportContext";

afterEach(() => vi.restoreAllMocks());

const MOCK_RECT = {
  x: 0, y: 0, top: 0, left: 0, right: 560, bottom: 700, width: 560, height: 700,
  toJSON: () => ({}),
};

function mockSvgRect() {
  const graph = screen.getByTestId("interactive-graph-svg");
  Object.defineProperty(graph, "getBoundingClientRect", { value: () => MOCK_RECT, configurable: true });
  return graph;
}

function GraphPointProbe() {
  const { graphPointAt } = useGraphViewport();
  const point = graphPointAt({ x: 280, y: 350 }); // dead center of the mocked 560x700 rect
  return <text data-testid="probe">{`${point.x.toFixed(1)},${point.y.toFixed(1)}`}</text>;
}

describe("InteractiveGraphViewport", () => {
  it("exposes graphPointAt through context to a nested child", () => {
    render(
      <InteractiveGraphViewport ariaLabel="test graph">
        <GraphPointProbe />
      </InteractiveGraphViewport>,
    );
    mockSvgRect();

    // Default camera centers (baseWidth/2, baseHeight/2) = (280, 350) on
    // the viewport's own center screen pixel -- this is the one exact
    // value the conversion must produce with no pan/zoom applied yet.
    expect(screen.getByTestId("probe").textContent).toBe("280.0,350.0");
  });

  it("useGraphViewport throws when called outside a provider", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    function Orphan() {
      useGraphViewport();
      return null;
    }

    expect(() => render(<Orphan />)).toThrow(
      /useGraphViewport must be called from within an InteractiveGraphViewport/,
    );
  });

  it("pointer-down on a [data-graph-node] element does not pan the canvas", () => {
    const { container } = render(
      <InteractiveGraphViewport ariaLabel="test graph">
        <g data-graph-node="" data-testid="a-node">
          <circle r={5} />
        </g>
      </InteractiveGraphViewport>,
    );
    const graph = mockSvgRect();
    const viewport = screen.getByRole("region", { name: "Etkileşimli teknik grafik" });
    const node = screen.getByTestId("a-node");
    const initialViewBox = graph.getAttribute("viewBox");

    fireEvent(node, new MouseEvent("pointerdown", { bubbles: true, clientX: 100, clientY: 100 }));
    fireEvent(viewport, new MouseEvent("pointermove", { bubbles: true, clientX: 200, clientY: 200 }));
    fireEvent(viewport, new MouseEvent("pointerup", { bubbles: true, clientX: 200, clientY: 200 }));

    expect(graph.getAttribute("viewBox")).toBe(initialViewBox);
    expect(container.querySelector(".is-dragging")).toBeNull();
  });

  it("pointer-down on empty canvas (no [data-graph-node] ancestor) still pans", () => {
    render(
      <InteractiveGraphViewport ariaLabel="test graph">
        <circle data-testid="plain-circle" r={5} />
      </InteractiveGraphViewport>,
    );
    const graph = mockSvgRect();
    const viewport = screen.getByRole("region", { name: "Etkileşimli teknik grafik" });
    const initialViewBox = graph.getAttribute("viewBox");

    fireEvent(viewport, new MouseEvent("pointerdown", { bubbles: true, clientX: 100, clientY: 100 }));
    fireEvent(viewport, new MouseEvent("pointermove", { bubbles: true, clientX: 200, clientY: 200 }));
    fireEvent(viewport, new MouseEvent("pointerup", { bubbles: true, clientX: 200, clientY: 200 }));

    expect(graph.getAttribute("viewBox")).not.toBe(initialViewBox);
  });
});
