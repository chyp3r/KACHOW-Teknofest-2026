import { describe, expect, it, vi } from "vitest";
import type { GraphEdge, GraphNode, KnowledgeGraph } from "../../types/documents";
import { createForceSimulation, layoutForceDirected } from "./forceLayout";

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

describe("createForceSimulation", () => {
  it("stepping N times matches the batch layout's N-iteration result -- same physics core", () => {
    const graph = smallGraph();
    const batch = layoutForceDirected(graph, { iterations: 40 });

    const simulation = createForceSimulation(graph);
    for (let i = 0; i < 40; i++) simulation.step();

    for (const n of graph.nodes) {
      expect(simulation.positions[n.id]).toEqual(batch.positions[n.id]);
    }
  });

  it("one step changes at least one node's position", () => {
    const simulation = createForceSimulation(smallGraph());
    const before = { ...simulation.positions["doc:a"] };

    simulation.step();

    expect(simulation.positions["doc:a"]).not.toEqual(before);
  });

  it("alpha decays toward settled, and isSettled() flips once it gets there", () => {
    const simulation = createForceSimulation(smallGraph());
    expect(simulation.isSettled()).toBe(false);

    for (let i = 0; i < 1000; i++) simulation.step();

    expect(simulation.isSettled()).toBe(true);
    expect(simulation.alpha).toBeLessThanOrEqual(0.001);
  });

  it("reheat() un-settles a settled simulation", () => {
    const simulation = createForceSimulation(smallGraph());
    for (let i = 0; i < 1000; i++) simulation.step();
    expect(simulation.isSettled()).toBe(true);

    simulation.reheat();

    expect(simulation.isSettled()).toBe(false);
  });

  it("reheat() never lowers alpha below its current value", () => {
    const simulation = createForceSimulation(smallGraph());
    // Freshly seeded alpha is 1 -- reheating to 0.3 must not drop it.
    simulation.reheat(0.3);
    expect(simulation.alpha).toBe(1);
  });

  it("a pinned node holds its exact position across many steps while an unpinned neighbour moves", () => {
    const simulation = createForceSimulation(smallGraph());
    simulation.pin("doc:a", 123, 456);

    for (let i = 0; i < 60; i++) simulation.step();

    expect(simulation.positions["doc:a"]).toEqual({ x: 123, y: 456 });
    // entity:tbmm is connected to the pinned node and repulsed by the
    // others -- it must not also be frozen in place.
    const tbmm = simulation.positions["entity:tbmm"];
    expect(tbmm.x !== 123 || tbmm.y !== 456).toBe(true);
  });

  it("isPinned() reflects pin/unpin state", () => {
    const simulation = createForceSimulation(smallGraph());
    expect(simulation.isPinned("doc:a")).toBe(false);

    simulation.pin("doc:a", 1, 1);
    expect(simulation.isPinned("doc:a")).toBe(true);

    simulation.unpin("doc:a");
    expect(simulation.isPinned("doc:a")).toBe(false);
  });

  it("unpin() lets a previously pinned node move again", () => {
    const simulation = createForceSimulation(smallGraph());
    simulation.pin("doc:a", 10, 10);
    for (let i = 0; i < 10; i++) simulation.step();
    simulation.unpin("doc:a");
    const afterUnpin = { ...simulation.positions["doc:a"] };

    for (let i = 0; i < 30; i++) simulation.step();

    expect(simulation.positions["doc:a"]).not.toEqual(afterUnpin);
  });

  it("syncGraph keeps the position of every surviving node id", () => {
    const graph = smallGraph();
    const simulation = createForceSimulation(graph);
    for (let i = 0; i < 30; i++) simulation.step();
    const tbmmBefore = { ...simulation.positions["entity:tbmm"] };

    // Drop entity:nato, keep everything else -- e.g. a node-type filter
    // toggling off "entity" would not do this (it removes ALL entities),
    // but an edge-type filter narrowing which entities have any visible
    // edge could plausibly shrink the node set by one.
    const narrowed: KnowledgeGraph = {
      ...graph,
      nodes: graph.nodes.filter((n) => n.id !== "entity:nato"),
      edges: graph.edges.filter((e) => e.target !== "entity:nato"),
    };
    simulation.syncGraph(narrowed);

    expect(simulation.positions["entity:tbmm"]).toEqual(tbmmBefore);
    expect(simulation.positions["entity:nato"]).toBeUndefined();
  });

  it("syncGraph seeds a genuinely new node id without touching survivors", () => {
    const graph = smallGraph();
    const simulation = createForceSimulation(graph);
    for (let i = 0; i < 30; i++) simulation.step();
    const tbmmBefore = { ...simulation.positions["entity:tbmm"] };

    const withNewNode: KnowledgeGraph = {
      ...graph,
      nodes: [...graph.nodes, node("entity:brand-new")],
    };
    simulation.syncGraph(withNewNode);

    expect(simulation.positions["entity:tbmm"]).toEqual(tbmmBefore);
    expect(simulation.positions["entity:brand-new"]).toBeDefined();
  });

  it("syncGraph clears pinned state for a node id that no longer exists", () => {
    const graph = smallGraph();
    const simulation = createForceSimulation(graph);
    simulation.pin("entity:nato", 5, 5);

    const narrowed: KnowledgeGraph = {
      ...graph,
      nodes: graph.nodes.filter((n) => n.id !== "entity:nato"),
      edges: graph.edges.filter((e) => e.target !== "entity:nato"),
    };
    simulation.syncGraph(narrowed);

    expect(simulation.isPinned("entity:nato")).toBe(false);
  });
});
