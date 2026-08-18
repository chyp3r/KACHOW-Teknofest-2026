import { describe, expect, it, vi } from "vitest";
import type { GraphEdge, GraphNode, KnowledgeGraph } from "../../types/documents";
import { layoutForceDirected } from "./forceLayout";

function node(id: string, nodeType: GraphNode["node_type"] = "entity"): GraphNode {
  return {
    id, node_type: nodeType, label: id,
    storage_path: null, file_name: null, document_type_label: null,
    compliance_status: null, has_analysis: null,
    kanun: null, madde: null, field_labels: [], document_count: null,
    entity_kind: null, surface_forms: [], attributes: {},
  };
}

function edge(source: string, target: string, edgeType: GraphEdge["edge_type"] = "bahseder"): GraphEdge {
  return {
    source, target, edge_type: edgeType, source_kind: "llm",
    field_key: null, field_label: null, severity: null,
    reason: null, aciklama: null, raw: null,
  };
}

function smallGraph(): KnowledgeGraph {
  return {
    nodes: [node("doc:a"), node("entity:tbmm"), node("entity:nato"), node("madde:2646:17", "madde")],
    edges: [
      edge("doc:a", "entity:tbmm", "muhatap"),
      edge("doc:a", "entity:nato", "bahseder"),
      edge("doc:a", "madde:2646:17", "ihlal"),
    ],
    insights: {
      document_count: 1, madde_count: 1, kanun_count: 0, entity_count: 2, konu_count: 0,
      rule_edge_count: 2, llm_edge_count: 1, unresolved_reference_count: 0,
      top_breached_madde: null,
    },
  };
}

describe("layoutForceDirected", () => {
  it("produces byte-identical positions across two independent invocations", () => {
    const graph = smallGraph();

    const first = layoutForceDirected(graph);
    const second = layoutForceDirected(graph);

    expect(first).toEqual(second);
  });

  it("never calls Math.random -- seeded PRNG only", () => {
    const spy = vi.spyOn(Math, "random").mockImplementation(() => {
      throw new Error("layoutForceDirected must not call Math.random");
    });
    try {
      expect(() => layoutForceDirected(smallGraph())).not.toThrow();
    } finally {
      spy.mockRestore();
    }
  });

  it("is independent of the input node/edge array order", () => {
    const graph = smallGraph();
    const baseline = layoutForceDirected(graph);

    const shuffled: KnowledgeGraph = {
      ...graph,
      nodes: [...graph.nodes].reverse(),
      edges: [...graph.edges].reverse(),
    };
    const result = layoutForceDirected(shuffled);

    for (const n of graph.nodes) {
      expect(result.positions[n.id]).toEqual(baseline.positions[n.id]);
    }
  });

  it("produces a position for every node, and only for existing nodes", () => {
    const graph = smallGraph();

    const layout = layoutForceDirected(graph);

    expect(Object.keys(layout.positions).sort()).toEqual(
      graph.nodes.map((n) => n.id).sort(),
    );
  });

  it("keeps every position finite -- no NaN/Infinity from degenerate force math", () => {
    const layout = layoutForceDirected(smallGraph());

    for (const pos of Object.values(layout.positions)) {
      expect(Number.isFinite(pos.x)).toBe(true);
      expect(Number.isFinite(pos.y)).toBe(true);
    }
  });

  it("handles an empty graph without raising", () => {
    const empty: KnowledgeGraph = {
      nodes: [], edges: [],
      insights: {
        document_count: 0, madde_count: 0, kanun_count: 0, entity_count: 0, konu_count: 0,
        rule_edge_count: 0, llm_edge_count: 0, unresolved_reference_count: 0,
        top_breached_madde: null,
      },
    };

    const layout = layoutForceDirected(empty);

    expect(layout.positions).toEqual({});
  });

  it("a single isolated node still gets a position", () => {
    const graph: KnowledgeGraph = {
      nodes: [node("entity:lonely")],
      edges: [],
      insights: {
        document_count: 0, madde_count: 0, kanun_count: 0, entity_count: 1, konu_count: 0,
        rule_edge_count: 0, llm_edge_count: 0, unresolved_reference_count: 0,
        top_breached_madde: null,
      },
    };

    const layout = layoutForceDirected(graph);

    expect(layout.positions["entity:lonely"]).toBeDefined();
  });
});
