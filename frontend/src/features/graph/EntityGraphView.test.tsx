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

describe("EntityGraphView", () => {
  it("clicking a node opens the inspector with that node's data", () => {
    const { container } = render(<EntityGraphView graph={buildGraph()} />);

    fireEvent.click(container.querySelector('[data-node-id="entity:tbmm"]')!);

    const inspector = screen.getByRole("complementary", { name: /düğüm ayrıntıları/i });
    expect(inspector).toBeInTheDocument();
    expect(within(inspector).getByRole("heading", { name: "TBMM" })).toBeInTheDocument();
  });

  it("the entity inspector discloses every merged surface form", () => {
    const { container } = render(<EntityGraphView graph={buildGraph()} />);

    fireEvent.click(container.querySelector('[data-node-id="entity:tbmm"]')!);

    const inspector = screen.getByRole("complementary", { name: /düğüm ayrıntıları/i });
    expect(within(inspector).getByText("TÜRKİYE BÜYÜK MİLLET MECLİSİ")).toBeInTheDocument();
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

    fireEvent.click(container.querySelector('[data-node-id="doc:a.pdf"]')!);
    fireEvent.click(screen.getByRole("button", { name: /belgeyi aç/i }));

    expect(onSelectDocument).toHaveBeenCalledWith("a.pdf");
  });
});
