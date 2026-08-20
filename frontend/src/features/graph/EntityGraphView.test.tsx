import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { GraphEdge, GraphNode, KnowledgeGraph } from "../../types/documents";
import { EntityGraphView } from "./EntityGraphView";

function node(overrides: Partial<GraphNode> & { id: string; node_type: GraphNode["node_type"] }): GraphNode {
  return {
    label: overrides.id, storage_path: null, file_name: null, document_type_label: null,
    compliance_status: null, has_analysis: null,
    kanun: null, madde: null, field_labels: [], document_count: null,
    entity_kind: null, surface_forms: [], attributes: {},
    ...overrides,
  };
}

function edge(source: string, target: string, edgeType: GraphEdge["edge_type"], sourceKind: GraphEdge["source_kind"]): GraphEdge {
  return {
    source, target, edge_type: edgeType, source_kind: sourceKind,
    field_key: null, field_label: null, severity: null, reason: null, aciklama: null, raw: null,
  };
}

function buildGraph(): KnowledgeGraph {
  return {
    nodes: [
      node({ id: "doc:a.pdf", node_type: "document", storage_path: "a.pdf", label: "a.pdf" }),
      node({
        id: "entity:tbmm", node_type: "entity", label: "TBMM", entity_kind: "kurum",
        surface_forms: ["TBMM", "TÜRKİYE BÜYÜK MİLLET MECLİSİ"], document_count: 1,
      }),
      node({ id: "madde:2646:17", node_type: "madde", label: "m.17", kanun: "2646", madde: "17", document_count: 1 }),
      node({ id: "kanun:2646", node_type: "kanun", label: "RYUEHY", kanun: "2646" }),
    ],
    edges: [
      edge("doc:a.pdf", "entity:tbmm", "muhatap", "rule"),
      edge("doc:a.pdf", "madde:2646:17", "ihlal", "rule"),
      edge("doc:a.pdf", "kanun:2646", "atif", "llm"),
    ],
    insights: {
      document_count: 1, madde_count: 1, kanun_count: 1, entity_count: 1, konu_count: 0,
      rule_edge_count: 2, llm_edge_count: 1, unresolved_reference_count: 0,
      top_breached_madde: {
        madde_id: "madde:2646:17", kanun: "2646", madde: "17", field_labels: [], document_count: 1,
      },
    },
  };
}

const MOCK_SVG_RECT = {
  x: 0, y: 0, top: 0, left: 0, right: 900, bottom: 700, width: 900, height: 700,
  toJSON: () => ({}),
};

/** Every drag/graphPointAt test needs the SVG to report a real bounding
 * rect -- jsdom never lays anything out, so `getBoundingClientRect`
 * returns all zeros unless stubbed, exactly like
 * `InteractiveGraphViewport.test.tsx`'s own `mockSvgRect`. */
function mockSvgRect(container: HTMLElement) {
  const svg = container.querySelector('[data-testid="interactive-graph-svg"]') as SVGSVGElement;
  Object.defineProperty(svg, "getBoundingClientRect", { value: () => MOCK_SVG_RECT, configurable: true });
  return svg;
}

/** A plain click: press and release at the same point, no movement --
 * dispatched as MouseEvents named "pointerdown"/"pointerup" because jsdom
 * has no PointerEvent constructor (same technique
 * DecisionFlow.test.tsx and InteractiveGraphViewport.test.tsx already
 * use; React's synthetic event system dispatches by the native event's
 * `type` string, not its class). */
function firePointerClick(element: Element, clientX = 100, clientY = 100) {
  fireEvent(element, new MouseEvent("pointerdown", { bubbles: true, clientX, clientY }));
  fireEvent(element, new MouseEvent("pointerup", { bubbles: true, clientX, clientY }));
}

/** A drag: press on `element`, move past the click threshold, release. */
function fireDrag(element: Element, from: { x: number; y: number }, to: { x: number; y: number }) {
  fireEvent(element, new MouseEvent("pointerdown", { bubbles: true, clientX: from.x, clientY: from.y }));
  fireEvent(element, new MouseEvent("pointermove", { bubbles: true, clientX: to.x, clientY: to.y }));
  fireEvent(element, new MouseEvent("pointerup", { bubbles: true, clientX: to.x, clientY: to.y }));
}

describe("EntityGraphView", () => {
  it("clicking a node opens the inspector with that node's data", () => {
    const { container } = render(<EntityGraphView graph={buildGraph()} />);
    mockSvgRect(container);

    firePointerClick(container.querySelector('[data-node-id="entity:tbmm"]')!);

    const inspector = screen.getByRole("complementary", { name: /düğüm ayrıntıları/i });
    expect(inspector).toBeInTheDocument();
    expect(within(inspector).getByRole("heading", { name: "TBMM" })).toBeInTheDocument();
  });

  it("the entity inspector discloses every merged surface form", () => {
    const { container } = render(<EntityGraphView graph={buildGraph()} />);
    mockSvgRect(container);

    firePointerClick(container.querySelector('[data-node-id="entity:tbmm"]')!);

    const inspector = screen.getByRole("complementary", { name: /düğüm ayrıntıları/i });
    expect(within(inspector).getByText("TÜRKİYE BÜYÜK MİLLET MECLİSİ")).toBeInTheDocument();
  });

  it("a drag past the click threshold pins the node and does not open the inspector", () => {
    const { container } = render(<EntityGraphView graph={buildGraph()} />);
    mockSvgRect(container);
    const target = container.querySelector('[data-node-id="entity:tbmm"]')!;

    fireDrag(target, { x: 100, y: 100 }, { x: 160, y: 160 });

    expect(screen.queryByRole("complementary", { name: /düğüm ayrıntıları/i })).not.toBeInTheDocument();
    expect(target).toHaveClass("is-pinned");
  });

  it("a click without movement opens the inspector without pinning", () => {
    const { container } = render(<EntityGraphView graph={buildGraph()} />);
    mockSvgRect(container);
    const target = container.querySelector('[data-node-id="entity:tbmm"]')!;

    firePointerClick(target);

    expect(screen.getByRole("complementary", { name: /düğüm ayrıntıları/i })).toBeInTheDocument();
    expect(target).not.toHaveClass("is-pinned");
  });

  it("dragging a node updates its rendered position to follow the cursor", () => {
    const { container } = render(<EntityGraphView graph={buildGraph()} />);
    mockSvgRect(container);
    const target = container.querySelector('[data-node-id="entity:tbmm"]')!;
    const circleBefore = target.querySelector("circle")!;
    const before = { cx: circleBefore.getAttribute("cx"), cy: circleBefore.getAttribute("cy") };

    fireDrag(target, { x: 100, y: 100 }, { x: 400, y: 300 });

    const circleAfter = container.querySelector('[data-node-id="entity:tbmm"] circle')!;
    expect({ cx: circleAfter.getAttribute("cx"), cy: circleAfter.getAttribute("cy") }).not.toEqual(before);
  });

  it("double-clicking a pinned node unpins it", () => {
    const { container } = render(<EntityGraphView graph={buildGraph()} />);
    mockSvgRect(container);
    const target = container.querySelector('[data-node-id="entity:tbmm"]')!;
    fireDrag(target, { x: 100, y: 100 }, { x: 160, y: 160 });
    expect(target).toHaveClass("is-pinned");

    fireEvent.doubleClick(target);

    expect(target).not.toHaveClass("is-pinned");
  });

  it("the inspector's unpin button unpins a dragged node", () => {
    const { container } = render(<EntityGraphView graph={buildGraph()} />);
    mockSvgRect(container);
    const target = container.querySelector('[data-node-id="entity:tbmm"]')!;
    fireDrag(target, { x: 100, y: 100 }, { x: 160, y: 160 });
    expect(target).toHaveClass("is-pinned");

    // A second, plain click (no movement) opens the inspector on the
    // now-pinned node -- exactly how a user reaches the unpin button.
    firePointerClick(target);
    const inspector = screen.getByRole("complementary", { name: /düğüm ayrıntıları/i });
    expect(within(inspector).getByText(/sabitlendi/i)).toBeInTheDocument();

    fireEvent.click(within(inspector).getByRole("button", { name: /sabitlemeyi kaldır/i }));

    expect(container.querySelector('[data-node-id="entity:tbmm"]')).not.toHaveClass("is-pinned");
  });

  it("opening the inspector leaves the viewBox unchanged -- regression for the resize-reset bug", () => {
    const { container } = render(<EntityGraphView graph={buildGraph()} />);
    const svg = mockSvgRect(container);
    const initialViewBox = svg.getAttribute("viewBox");

    firePointerClick(container.querySelector('[data-node-id="entity:tbmm"]')!);

    expect(screen.getByRole("complementary", { name: /düğüm ayrıntıları/i })).toBeInTheDocument();
    expect(svg.getAttribute("viewBox")).toBe(initialViewBox);
  });

  it("unchecking an edge-type filter removes matching edges from the rendered graph", () => {
    const { container } = render(<EntityGraphView graph={buildGraph()} />);

    expect(container.querySelectorAll('[data-edge-type="atif"]')).toHaveLength(1);

    fireEvent.click(screen.getByRole("checkbox", { name: /mevzuat atfı/i }));

    expect(container.querySelectorAll('[data-edge-type="atif"]')).toHaveLength(0);
    // an unrelated edge type must be unaffected by toggling this one
    expect(container.querySelectorAll('[data-edge-type="ihlal"]')).toHaveLength(1);
  });

  it("switching to the compliance-only preset reproduces the v1 bipartite view", () => {
    const { container } = render(<EntityGraphView graph={buildGraph()} />);

    fireEvent.click(screen.getByRole("button", { name: /sadece uyum/i }));

    // .ribbon-rule/.ribbon-llm and .kanun-band are KnowledgeGraphView's own
    // markup -- their presence proves the preset renders that component,
    // not a re-implementation of it.
    expect(container.querySelector(".ribbon-rule")).not.toBeNull();
    // Entity nodes have no place in the compliance-only view.
    expect(container.querySelector('[data-node-id="entity:tbmm"]')).toBeNull();
  });

  it("shows a loading spinner while loading", () => {
    render(<EntityGraphView graph={null} loading />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows an empty state for an empty graph", () => {
    const empty: KnowledgeGraph = {
      nodes: [], edges: [],
      insights: {
        document_count: 0, madde_count: 0, kanun_count: 0, entity_count: 0, konu_count: 0,
        rule_edge_count: 0, llm_edge_count: 0, unresolved_reference_count: 0,
        top_breached_madde: null,
      },
    };
    render(<EntityGraphView graph={empty} />);
    expect(screen.getByText(/evrak yok|henüz|bulunamadı/i)).toBeInTheDocument();
  });

  it("clicking a document node's open-document action calls onSelectDocument", () => {
    const onSelectDocument = vi.fn();
    const { container } = render(<EntityGraphView graph={buildGraph()} onSelectDocument={onSelectDocument} />);
    mockSvgRect(container);

    firePointerClick(container.querySelector('[data-node-id="doc:a.pdf"]')!);
    fireEvent.click(screen.getByRole("button", { name: /belgeyi aç/i }));

    expect(onSelectDocument).toHaveBeenCalledWith("a.pdf");
  });
});
