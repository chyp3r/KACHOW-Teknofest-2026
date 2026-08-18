import { describe, expect, it } from "vitest";
import type { GraphEdge, GraphNode, KnowledgeGraph } from "../../types/documents";
import { layoutBipartite, ribbonPath, truncateLabel } from "./layout";

function documentNode(id: string, label = id): GraphNode {
  return {
    id: `doc:${id}`,
    node_type: "document",
    label,
    storage_path: id,
    file_name: label,
    document_type_label: "Resmî Yazı",
    compliance_status: "incomplete",
    has_analysis: true,
    kanun: null,
    madde: null,
    field_labels: [],
    document_count: null,
    entity_kind: null,
    surface_forms: [],
    attributes: {},
  };
}

function maddeNode(kanun: string, madde: string, documentCount: number, fieldLabels: string[] = []): GraphNode {
  return {
    id: `madde:${kanun}:${madde}`,
    node_type: "madde",
    label: `m.${madde}`,
    storage_path: null,
    file_name: null,
    document_type_label: null,
    compliance_status: null,
    has_analysis: null,
    kanun,
    madde,
    field_labels: fieldLabels,
    document_count: documentCount,
    entity_kind: null,
    surface_forms: [],
    attributes: {},
  };
}

function kanunNode(kanun: string, label: string): GraphNode {
  return {
    id: `kanun:${kanun}`,
    node_type: "kanun",
    label,
    storage_path: null,
    file_name: null,
    document_type_label: null,
    compliance_status: null,
    has_analysis: null,
    kanun,
    madde: null,
    field_labels: [],
    document_count: null,
    entity_kind: null,
    surface_forms: [],
    attributes: {},
  };
}

function ihlalEdge(source: string, target: string): GraphEdge {
  return {
    source, target, edge_type: "ihlal", source_kind: "rule",
    field_key: "sayi", field_label: "Sayı", severity: "zorunlu",
    reason: "Zorunlu.", aciklama: null, raw: null,
  };
}

describe("layoutBipartite", () => {
  it("sorts documents by breach count descending, with a stable id tiebreak", () => {
    const graph: KnowledgeGraph = {
      nodes: [
        documentNode("a.pdf"), documentNode("b.pdf"), documentNode("c.pdf"),
        maddeNode("2646", "17", 2),
        kanunNode("2646", "RYUEHY"),
      ],
      edges: [
        // a.pdf: 1 breach, b.pdf: 2 breaches, c.pdf: 0 breaches
        ihlalEdge("doc:a.pdf", "madde:2646:17"),
        ihlalEdge("doc:b.pdf", "madde:2646:17"),
        ihlalEdge("doc:b.pdf", "madde:2646:17"),
      ],
      insights: {
        document_count: 3, madde_count: 1, kanun_count: 1, entity_count: 0, konu_count: 0,
        rule_edge_count: 3, llm_edge_count: 0, unresolved_reference_count: 0,
        top_breached_madde: null,
      },
    };

    const layout = layoutBipartite(graph);

    expect(layout.documentRows.map((row) => row.node.id)).toEqual([
      "doc:b.pdf", // 2 breaches
      "doc:a.pdf", // 1 breach
      "doc:c.pdf", // 0 breaches
    ]);
  });

  it("breaks ties on equal breach count by node id, ascending", () => {
    const graph: KnowledgeGraph = {
      nodes: [documentNode("z.pdf"), documentNode("a.pdf")],
      edges: [],
      insights: {
        document_count: 2, madde_count: 0, kanun_count: 0, entity_count: 0, konu_count: 0,
        rule_edge_count: 0, llm_edge_count: 0, unresolved_reference_count: 0,
        top_breached_madde: null,
      },
    };

    const layout = layoutBipartite(graph);

    expect(layout.documentRows.map((row) => row.node.id)).toEqual(["doc:a.pdf", "doc:z.pdf"]);
  });

  it("sorts maddeler by distinct-document in-degree descending within their kanun band", () => {
    const graph: KnowledgeGraph = {
      nodes: [
        maddeNode("2646", "17", 5),
        maddeNode("2646", "10", 1),
        maddeNode("2646", "14", 3),
        kanunNode("2646", "RYUEHY"),
      ],
      edges: [],
      insights: {
        document_count: 0, madde_count: 3, kanun_count: 1, entity_count: 0, konu_count: 0,
        rule_edge_count: 0, llm_edge_count: 0, unresolved_reference_count: 0,
        top_breached_madde: null,
      },
    };

    const layout = layoutBipartite(graph);

    expect(layout.maddeRows.map((row) => row.node.id)).toEqual([
      "madde:2646:17", "madde:2646:14", "madde:2646:10",
    ]);
  });

  it("produces byte-identical output across two calls on the same input", () => {
    const graph: KnowledgeGraph = {
      nodes: [
        documentNode("a.pdf"), maddeNode("2646", "17", 1), kanunNode("2646", "RYUEHY"),
      ],
      edges: [ihlalEdge("doc:a.pdf", "madde:2646:17")],
      insights: {
        document_count: 1, madde_count: 1, kanun_count: 1, entity_count: 0, konu_count: 0,
        rule_edge_count: 1, llm_edge_count: 0, unresolved_reference_count: 0,
        top_breached_madde: null,
      },
    };

    const first = layoutBipartite(graph);
    const second = layoutBipartite(graph);

    expect(first).toEqual(second);
  });

  it("grows height linearly with document count and produces no overlapping rows", () => {
    const documents = Array.from({ length: 50 }, (_, i) => documentNode(`doc-${i}.pdf`));
    const small: KnowledgeGraph = {
      nodes: documents.slice(0, 5),
      edges: [],
      insights: {
        document_count: 5, madde_count: 0, kanun_count: 0, entity_count: 0, konu_count: 0,
        rule_edge_count: 0, llm_edge_count: 0, unresolved_reference_count: 0,
        top_breached_madde: null,
      },
    };
    const large: KnowledgeGraph = {
      nodes: documents,
      edges: [],
      insights: {
        document_count: 50, madde_count: 0, kanun_count: 0, entity_count: 0, konu_count: 0,
        rule_edge_count: 0, llm_edge_count: 0, unresolved_reference_count: 0,
        top_breached_madde: null,
      },
    };

    const smallLayout = layoutBipartite(small);
    const largeLayout = layoutBipartite(large);

    // Linear, not e.g. quadratic or clipped: the 45-row difference must
    // scale the height by the same per-row amount every time.
    const perRow = (largeLayout.height - smallLayout.height) / 45;
    expect(perRow).toBeGreaterThan(0);
    expect(largeLayout.height).toBeCloseTo(smallLayout.height + perRow * 45, 5);

    const ys = largeLayout.documentRows.map((row) => row.y);
    const uniqueYs = new Set(ys);
    expect(uniqueYs.size).toBe(ys.length); // no two rows share a y position
  });

  it("renders a single kanun band spanning all of its maddeler", () => {
    const graph: KnowledgeGraph = {
      nodes: [
        maddeNode("2646", "17", 3), maddeNode("2646", "10", 1),
        kanunNode("2646", "RYUEHY"),
      ],
      edges: [],
      insights: {
        document_count: 0, madde_count: 2, kanun_count: 1, entity_count: 0, konu_count: 0,
        rule_edge_count: 0, llm_edge_count: 0, unresolved_reference_count: 0,
        top_breached_madde: null,
      },
    };

    const layout = layoutBipartite(graph);

    expect(layout.kanunBands).toHaveLength(1);
    expect(layout.kanunBands[0].node.id).toBe("kanun:2646");
  });
});

describe("ribbonPath", () => {
  it("starts and ends exactly at the given coordinates", () => {
    const path = ribbonPath(10, 20, 300, 220);

    expect(path.startsWith("M 10 20")).toBe(true);
    expect(path.endsWith("300 220")).toBe(true);
  });
});

describe("truncateLabel", () => {
  it("leaves a short label untouched", () => {
    expect(truncateLabel("kısa", 40)).toBe("kısa");
  });

  it("truncates a long label with an ellipsis, never exceeding maxLength", () => {
    const long = "a".repeat(80);
    const truncated = truncateLabel(long, 40);

    expect(truncated.length).toBeLessThanOrEqual(40);
    expect(truncated.endsWith("…")).toBe(true);
  });
});
