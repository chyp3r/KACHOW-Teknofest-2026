import { ApiError, apiRequest } from "./apiClient";
import type { CorpusGraph, GraphEdge, GraphNode, KnowledgeGraph } from "../types/documents";
import { documentService } from "./documentService";

function edgeKey(edge: GraphEdge): string {
  return [edge.source, edge.target, edge.edge_type, edge.source_kind, edge.field_key ?? "", edge.raw ?? ""].join("|");
}

export function mergeDocumentGraphs(
  graphs: KnowledgeGraph[],
  totalDocumentCount: number,
  hiddenDocumentCount: number,
): CorpusGraph {
  const nodesById = new Map<string, GraphNode>();
  const edgesByKey = new Map<string, GraphEdge>();
  let unresolvedReferenceCount = 0;

  for (const graph of graphs) {
    unresolvedReferenceCount += graph.insights.unresolved_reference_count;
    for (const node of graph.nodes) {
      const current = nodesById.get(node.id);
      nodesById.set(node.id, current ? {
        ...current,
        ...node,
        field_labels: [...new Set([...current.field_labels, ...node.field_labels])],
        surface_forms: [...new Set([...current.surface_forms, ...node.surface_forms])],
        attributes: { ...current.attributes, ...node.attributes },
      } : { ...node });
    }
    for (const edge of graph.edges) edgesByKey.set(edgeKey(edge), edge);
  }

  const edges = [...edgesByKey.values()];
  const documentSourcesByTarget = new Map<string, Set<string>>();
  for (const edge of edges) {
    const source = nodesById.get(edge.source);
    if (source?.node_type !== "document") continue;
    const sources = documentSourcesByTarget.get(edge.target) ?? new Set<string>();
    sources.add(source.id);
    documentSourcesByTarget.set(edge.target, sources);
  }
  for (const [target, sources] of documentSourcesByTarget) {
    const node = nodesById.get(target);
    if (node && node.node_type !== "document") nodesById.set(target, { ...node, document_count: sources.size });
  }

  const nodes = [...nodesById.values()];
  const breachCounts = new Map<string, Set<string>>();
  for (const edge of edges) {
    if (edge.edge_type !== "ihlal" || nodesById.get(edge.target)?.node_type !== "madde") continue;
    const sources = breachCounts.get(edge.target) ?? new Set<string>();
    sources.add(edge.source);
    breachCounts.set(edge.target, sources);
  }
  const topBreach = [...breachCounts.entries()].sort((left, right) => right[1].size - left[1].size)[0];
  const topNode = topBreach ? nodesById.get(topBreach[0]) : null;

  return {
    nodes,
    edges,
    insights: {
      document_count: nodes.filter((node) => node.node_type === "document").length,
      madde_count: nodes.filter((node) => node.node_type === "madde").length,
      kanun_count: nodes.filter((node) => node.node_type === "kanun").length,
      entity_count: nodes.filter((node) => node.node_type === "entity").length,
      konu_count: nodes.filter((node) => node.node_type === "konu").length,
      rule_edge_count: edges.filter((edge) => edge.source_kind === "rule").length,
      llm_edge_count: edges.filter((edge) => edge.source_kind === "llm").length,
      unresolved_reference_count: unresolvedReferenceCount,
      top_breached_madde: topNode && topBreach ? {
        madde_id: topNode.id,
        kanun: topNode.kanun ?? "Belirtilmedi",
        madde: topNode.madde ?? topNode.label,
        field_labels: topNode.field_labels,
        document_count: topBreach[1].size,
      } : null,
    },
    truncated: hiddenDocumentCount > 0,
    total_document_count: totalDocumentCount,
    hidden_document_count: hiddenDocumentCount,
    is_fallback: true,
  };
}

export const graphService = {
  async corpusGraph(): Promise<CorpusGraph> {
    try {
      return await apiRequest("/api/v1/documents/graph");
    } catch (error) {
      if (!(error instanceof ApiError) || error.status < 500) throw error;
      const documents = await documentService.list();
      const results = await Promise.allSettled(
        documents.map((document) => graphService.documentGraph(document.storage_path)),
      );
      const graphs = results
        .filter((result): result is PromiseFulfilledResult<KnowledgeGraph> => result.status === "fulfilled")
        .map((result) => result.value);
      if (graphs.length === 0 && documents.length > 0) throw error;
      return mergeDocumentGraphs(graphs, documents.length, results.length - graphs.length);
    }
  },
  documentGraph(storagePath: string): Promise<KnowledgeGraph> {
    const safePath = storagePath.split("/").map(encodeURIComponent).join("/");
    return apiRequest(`/api/v1/documents/${safePath}/graph`);
  },
};
