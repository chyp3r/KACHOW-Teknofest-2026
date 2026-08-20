import { describe, expect, it } from "vitest";
import type { GraphEdge, GraphNode, KnowledgeGraph } from "../../types/documents";
import { COMPLIANCE_ONLY_EDGE_TYPES, COMPLIANCE_ONLY_NODE_TYPES, filterGraph, filterToComplianceOnly } from "./filters";

function node(id: string, nodeType: GraphNode["node_type"], documentCount: number | null = null): GraphNode {
  return {
    id, node_type: nodeType, label: id,
    storage_path: nodeType === "document" ? id : null, file_name: null, document_type_label: null,
    compliance_status: null, has_analysis: null,
    kanun: null, madde: null, field_labels: [], document_count: documentCount,
    entity_kind: null, surface_forms: [], attributes: {},
  };
}

function edge(
  source: string,
  target: string,
  edgeType: GraphEdge["edge_type"],
  sourceKind: GraphEdge["source_kind"],
): GraphEdge {
  return {
    source, target, edge_type: edgeType, source_kind: sourceKind,
    field_key: null, field_label: null, severity: null, reason: null, aciklama: null, raw: null,
  };
}

function unifiedGraph(): KnowledgeGraph {
  return {
    nodes: [
      node("doc:a", "document"),
      node("madde:2646:17", "madde", 1),
      node("kanun:2646", "kanun"),
      node("entity:tbmm", "entity", 1),
      node("konu:x", "konu", 1),
    ],
    edges: [
      edge("doc:a", "madde:2646:17", "ihlal", "rule"),
      edge("doc:a", "kanun:2646", "atif", "llm"),
      edge("doc:a", "entity:tbmm", "muhatap", "rule"),
      edge("doc:a", "entity:tbmm", "bahseder", "llm"),
      edge("doc:a", "konu:x", "konu", "rule"),
    ],
    insights: {
      document_count: 1, madde_count: 1, kanun_count: 1, entity_count: 1, konu_count: 1,
      rule_edge_count: 3, llm_edge_count: 2, unresolved_reference_count: 0,
      top_breached_madde: {
        madde_id: "madde:2646:17", kanun: "2646", madde: "17", field_labels: ["Sayı"], document_count: 1,
      },
    },
  };
}

describe("filterGraph", () => {
  it("drops nodes outside the allowed node types", () => {
    const result = filterGraph(unifiedGraph(), { nodeTypes: new Set(["document", "entity"]) });
    expect(result.nodes.map((n) => n.node_type).sort()).toEqual(["document", "entity"]);
  });

  it("drops edges outside the allowed edge types without touching node presence", () => {
    const result = filterGraph(unifiedGraph(), { edgeTypes: new Set(["ihlal"]) });
    expect(result.edges).toHaveLength(1);
    expect(result.edges[0].edge_type).toBe("ihlal");
    expect(result.nodes).toHaveLength(unifiedGraph().nodes.length); // all nodes still present
  });

  it("drops an edge whose endpoint was removed by the node-type filter, even if the edge type is allowed", () => {
    const result = filterGraph(unifiedGraph(), { nodeTypes: new Set(["document", "madde"]) });
    // the atif edge targets kanun:2646, which is now gone
    expect(result.edges.some((e) => e.edge_type === "atif")).toBe(false);
    expect(result.edges.some((e) => e.edge_type === "ihlal")).toBe(true);
  });

  it("recomputes per-type node counts and rule/llm edge counts from the filtered set", () => {
    const result = filterGraph(unifiedGraph(), { edgeTypes: new Set(["ihlal", "muhatap"]) });
    expect(result.insights.rule_edge_count).toBe(2); // ihlal + muhatap, both source_kind "rule"
    expect(result.insights.llm_edge_count).toBe(0);
  });

  it("passes unresolved_reference_count and top_breached_madde through unchanged", () => {
    const original = unifiedGraph();
    const result = filterGraph(original, { nodeTypes: new Set(["entity"]) });
    expect(result.insights.top_breached_madde).toEqual(original.insights.top_breached_madde);
    expect(result.insights.unresolved_reference_count).toBe(original.insights.unresolved_reference_count);
  });

  it("with no options, returns every node and edge unchanged", () => {
    const original = unifiedGraph();
    const result = filterGraph(original, {});
    expect(result.nodes).toHaveLength(original.nodes.length);
    expect(result.edges).toHaveLength(original.edges.length);
  });
});

describe("filterToComplianceOnly", () => {
  it("keeps only document/madde/kanun nodes and ihlal/atif edges", () => {
    const result = filterToComplianceOnly(unifiedGraph());
    expect(result.nodes.map((n) => n.node_type).sort()).toEqual(["document", "kanun", "madde"]);
    expect(result.edges.map((e) => e.edge_type).sort()).toEqual(["atif", "ihlal"]);
  });

  it("reproduces the v1 rule/llm edge split -- entity/konu edges must not inflate it", () => {
    const result = filterToComplianceOnly(unifiedGraph());
    // Only the ihlal edge is "rule" within the compliance-only subset --
    // the muhatap/konu rule edges (also source_kind "rule") must not count,
    // or the headline's "kural" number would be inflated by entity edges
    // that PR #212's shipped view never had.
    expect(result.insights.rule_edge_count).toBe(1);
    expect(result.insights.llm_edge_count).toBe(1);
  });

  it("the preset constants match what filterToComplianceOnly actually uses", () => {
    const viaConstants = filterGraph(unifiedGraph(), {
      nodeTypes: COMPLIANCE_ONLY_NODE_TYPES,
      edgeTypes: COMPLIANCE_ONLY_EDGE_TYPES,
    });
    expect(viaConstants).toEqual(filterToComplianceOnly(unifiedGraph()));
  });
});
