import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { GraphEdge, GraphNode, KnowledgeGraph } from "../../types/documents";
import { KnowledgeGraphView } from "./KnowledgeGraphView";

function documentNode(id: string, label: string): GraphNode {
  return {
    id: `doc:${id}`, node_type: "document", label,
    storage_path: id, file_name: label, document_type_label: "Resmî Yazı",
    compliance_status: "incomplete", has_analysis: true,
    kanun: null, madde: null, field_labels: [], document_count: null,
  };
}

function maddeNode(kanun: string, madde: string, documentCount: number, fieldLabels: string[]): GraphNode {
  return {
    id: `madde:${kanun}:${madde}`, node_type: "madde", label: `m.${madde}`,
    storage_path: null, file_name: null, document_type_label: null,
    compliance_status: null, has_analysis: null,
    kanun, madde, field_labels: fieldLabels, document_count: documentCount,
  };
}

function kanunNode(kanun: string, label: string): GraphNode {
  return {
    id: `kanun:${kanun}`, node_type: "kanun", label,
    storage_path: null, file_name: null, document_type_label: null,
    compliance_status: null, has_analysis: null,
    kanun, madde: null, field_labels: [], document_count: null,
  };
}

function ihlalEdge(source: string, target: string): GraphEdge {
  return {
    source, target, edge_type: "ihlal", source_kind: "rule",
    field_key: "imza_sahibi", field_label: "İmza sahibi", severity: "zorunlu",
    reason: "Belge imzalanmalıdır.", aciklama: null, raw: null,
  };
}

function atifEdge(source: string, target: string): GraphEdge {
  return {
    source, target, edge_type: "atif", source_kind: "llm",
    field_key: null, field_label: null, severity: null,
    reason: null, aciklama: "Model önerisi.", raw: "RYUEHY m.4",
  };
}

const RYUEHY_LABEL = "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik";

function buildGraph(): KnowledgeGraph {
  return {
    nodes: [
      documentNode("a.pdf", "a.pdf"),
      documentNode("b.pdf", "b.pdf"),
      maddeNode("2646", "17", 2, ["İmza sahibi"]),
      kanunNode("2646", RYUEHY_LABEL),
    ],
    edges: [
      ihlalEdge("doc:a.pdf", "madde:2646:17"),
      ihlalEdge("doc:b.pdf", "madde:2646:17"),
      atifEdge("doc:a.pdf", "madde:2646:17"),
    ],
    insights: {
      document_count: 2, madde_count: 1, kanun_count: 1,
      rule_edge_count: 2, llm_edge_count: 1, unresolved_reference_count: 0,
      top_breached_madde: {
        madde_id: "madde:2646:17", kanun: "2646", madde: "17",
        field_labels: ["İmza sahibi"], document_count: 2,
      },
    },
  };
}

describe("KnowledgeGraphView", () => {
  it("renders the headline from the computed top breached madde", () => {
    const { container } = render(<KnowledgeGraphView graph={buildGraph()} />);

    const headline = container.querySelector(".knowledge-graph-headline-text");
    expect(headline).not.toBeNull();
    expect(headline!.textContent).toMatch(/m\.17/);
    expect(headline!.textContent).toMatch(/İmza sahibi/);
    // "2 evrakın 2'sinde" -- the document_count on the winning madde, not
    // the raw edge count (2 rule edges here, same as document_count, but
    // this is the number that must come from insights, not len(edges)).
    expect(headline!.textContent).toMatch(/2 evrakın 2'sinde/);
  });

  it("renders one ribbon per rule edge with the rule class and one per llm edge with the llm class", () => {
    const { container } = render(<KnowledgeGraphView graph={buildGraph()} />);

    const rulePaths = container.querySelectorAll(".ribbon-rule");
    const llmPaths = container.querySelectorAll(".ribbon-llm");
    expect(rulePaths).toHaveLength(2);
    expect(llmPaths).toHaveLength(1);
  });

  it("dims non-incident ribbons when hovering a madde node", () => {
    const { container } = render(<KnowledgeGraphView graph={buildGraph()} />);

    const maddeEl = container.querySelector('[data-node-id="madde:2646:17"]');
    expect(maddeEl).not.toBeNull();
    fireEvent.mouseEnter(maddeEl!);

    // Every ribbon in this fixture touches madde:2646:17, so all three
    // should be highlighted (not dimmed) -- confirms the dim mechanism
    // keys off adjacency rather than always dimming everything on hover.
    const dimmed = container.querySelectorAll(".is-dimmed");
    expect(dimmed).toHaveLength(0);
  });

  it("dims ribbons not touching the hovered document", () => {
    const graph = buildGraph();
    // Add a second madde only b.pdf touches, so hovering a.pdf must dim
    // the edge into it.
    graph.nodes.push(maddeNode("2646", "10", 1, ["Gönderen idare"]));
    graph.edges.push(ihlalEdge("doc:b.pdf", "madde:2646:10"));
    const { container } = render(<KnowledgeGraphView graph={graph} />);

    const docEl = container.querySelector('[data-node-id="doc:a.pdf"]');
    fireEvent.mouseEnter(docEl!);

    const dimmed = container.querySelectorAll(".is-dimmed");
    expect(dimmed.length).toBeGreaterThan(0);
  });

  it("calls onSelectDocument with the storage_path when a document node is clicked", () => {
    const onSelectDocument = vi.fn();
    const { container } = render(
      <KnowledgeGraphView graph={buildGraph()} onSelectDocument={onSelectDocument} />,
    );

    const docEl = container.querySelector('[data-node-id="doc:a.pdf"]');
    fireEvent.click(docEl!);

    expect(onSelectDocument).toHaveBeenCalledWith("a.pdf");
  });

  it("shows a loading spinner instead of the graph while loading", () => {
    render(<KnowledgeGraphView graph={null} loading />);

    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows an empty state when the graph has no documents", () => {
    const empty: KnowledgeGraph = {
      nodes: [], edges: [],
      insights: {
        document_count: 0, madde_count: 0, kanun_count: 0,
        rule_edge_count: 0, llm_edge_count: 0, unresolved_reference_count: 0,
        top_breached_madde: null,
      },
    };

    render(<KnowledgeGraphView graph={empty} />);

    expect(screen.queryByText(/m\./)).not.toBeInTheDocument();
    expect(screen.getByText(/evrak yok|henüz|bulunamadı/i)).toBeInTheDocument();
  });

  it("renders a single header line, not a band legend, when the corpus cites only one kanun", () => {
    const { container } = render(<KnowledgeGraphView graph={buildGraph()} />);

    expect(container.querySelectorAll(".kanun-band")).toHaveLength(0);
    expect(screen.getByText(RYUEHY_LABEL)).toBeInTheDocument();
  });
});
