// Pure graph filtering -- no React, no DOM.
//
// Two independent filters: `nodeTypes` removes whole nodes (and, as a
// consequence, any edge touching a removed node), `edgeTypes` removes only
// edges of that type, leaving every node in place even if it ends up
// edgeless. This is what lets a jury turn off "model önerisi" edges without
// the graph losing the entities those edges pointed at.
//
// `filterToComplianceOnly` exists specifically so the unified graph's
// "compliance-only" preset can *reuse* the exact bipartite view PR #212
// shipped rather than reimplement it: filter first with this function, then
// hand the result to the unchanged `layoutBipartite`/`KnowledgeGraphView`.
// The one subtlety this file exists to get right: `GraphInsights.rule_edge_
// count`/`llm_edge_count` became *global* counts across every edge type once
// Entity/Konu edges were added (see knowledge_graph.py's v2 update) -- naively
// passing the original graph's insights through to the compliance-only view
// would show an inflated "kural" count that includes muhatap/gönderen/konu
// edges PR #212 never had. Recomputing insights from the *filtered* edge set
// is what keeps the reproduction honest.

import type { GraphEdge, GraphNode, GraphInsights, KnowledgeGraph } from "../../types/documents";

export interface GraphFilterOptions {
  //: `undefined` means "no restriction" -- every node type allowed.
  nodeTypes?: Set<GraphNode["node_type"]>;
  //: `undefined` means "no restriction" -- every edge type allowed.
  edgeTypes?: Set<GraphEdge["edge_type"]>;
}

export function filterGraph(graph: KnowledgeGraph, options: GraphFilterOptions): KnowledgeGraph {
  const { nodeTypes, edgeTypes } = options;

  const nodes = graph.nodes.filter((node) => !nodeTypes || nodeTypes.has(node.node_type));
  const nodeIds = new Set(nodes.map((node) => node.id));

  const edges = graph.edges.filter(
    (edge) =>
      nodeIds.has(edge.source) &&
      nodeIds.has(edge.target) &&
      (!edgeTypes || edgeTypes.has(edge.edge_type)),
  );

  const countByType = (nodeType: GraphNode["node_type"]) =>
    nodes.filter((node) => node.node_type === nodeType).length;
  const countByKind = (sourceKind: GraphEdge["source_kind"]) =>
    edges.filter((edge) => edge.source_kind === sourceKind).length;

  const insights: GraphInsights = {
    document_count: countByType("document"),
    madde_count: countByType("madde"),
    kanun_count: countByType("kanun"),
    entity_count: countByType("entity"),
    konu_count: countByType("konu"),
    rule_edge_count: countByKind("rule"),
    llm_edge_count: countByKind("llm"),
    // Neither is derivable from the filtered edge set -- an unresolved
    // reference produced no edge in the first place, and the headline's
    // top-breached-madde is already scoped to rule/ihlal edges by the
    // backend, so it stays valid regardless of which edge types this view
    // happens to be showing.
    unresolved_reference_count: graph.insights.unresolved_reference_count,
    top_breached_madde: graph.insights.top_breached_madde,
  };

  return { nodes, edges, insights };
}

export const COMPLIANCE_ONLY_NODE_TYPES = new Set<GraphNode["node_type"]>(["document", "madde", "kanun"]);
export const COMPLIANCE_ONLY_EDGE_TYPES = new Set<GraphEdge["edge_type"]>(["ihlal", "atif"]);

/** Reproduces exactly the graph PR #212 shipped, as a filter over the
 * unified v2 graph rather than a second builder. */
export function filterToComplianceOnly(graph: KnowledgeGraph): KnowledgeGraph {
  return filterGraph(graph, { nodeTypes: COMPLIANCE_ONLY_NODE_TYPES, edgeTypes: COMPLIANCE_ONLY_EDGE_TYPES });
}
