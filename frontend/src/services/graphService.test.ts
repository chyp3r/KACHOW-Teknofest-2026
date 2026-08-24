import { describe, expect, it } from "vitest";
import type { GraphNode, KnowledgeGraph } from "../types/documents";
import { mergeDocumentGraphs } from "./graphService";

function node(id: string, nodeType: GraphNode["node_type"], label: string): GraphNode {
  return {
    id,
    node_type: nodeType,
    label,
    storage_path: nodeType === "document" ? id : null,
    file_name: nodeType === "document" ? label : null,
    document_type_label: null,
    compliance_status: null,
    has_analysis: nodeType === "document",
    kanun: nodeType === "madde" ? "Örnek Kanun" : null,
    madde: nodeType === "madde" ? "Madde 1" : null,
    field_labels: [],
    document_count: nodeType === "document" ? null : 1,
    entity_kind: null,
    surface_forms: [],
    attributes: {},
  };
}

function graph(documentId: string): KnowledgeGraph {
  return {
    nodes: [node(documentId, "document", `${documentId}.pdf`), node("madde:1", "madde", "Madde 1")],
    edges: [{
      source: documentId,
      target: "madde:1",
      edge_type: "ihlal",
      source_kind: "rule",
      field_key: "sayi",
      field_label: "Sayı",
      severity: "high",
      reason: "Eksik",
      aciklama: null,
      raw: null,
    }],
    insights: {
      document_count: 1,
      madde_count: 1,
      kanun_count: 0,
      entity_count: 0,
      konu_count: 0,
      rule_edge_count: 1,
      llm_edge_count: 0,
      unresolved_reference_count: 0,
      top_breached_madde: null,
    },
  };
}

describe("mergeDocumentGraphs", () => {
  it("deduplicates shared legislation nodes and reports omitted documents", () => {
    const merged = mergeDocumentGraphs([graph("document:1"), graph("document:2")], 3, 1);

    expect(merged.nodes.filter((item) => item.id === "madde:1")).toHaveLength(1);
    expect(merged.nodes.find((item) => item.id === "madde:1")?.document_count).toBe(2);
    expect(merged.insights.top_breached_madde?.document_count).toBe(2);
    expect(merged).toMatchObject({ is_fallback: true, truncated: true, total_document_count: 3, hidden_document_count: 1 });
  });
});
