// Deterministic force-directed layout for the unified entity graph -- no
// React, no DOM.
//
// The v1 graph used a two-column bipartite layout because the data was
// genuinely bipartite (Document -> Madde/Kanun only). v2 adds Entity/Konu
// nodes and Document<->Entity<->Document paths, which is a general graph
// shape a bipartite layout cannot represent -- force-directed is the right
// tool here, but "force-directed" and "deterministic" are usually treated
// as opposites (real d3-force uses `Math.random()` for jitter and a
// time/alpha-based convergence check). Neither is true of this
// implementation:
//
// - Initial positions come from a seeded PRNG (mulberry32) consumed in
//   *sorted node-id order*, never `Math.random()`. Sorting first is what
//   makes the output independent of the order nodes/edges arrive in --
//   the same discipline `layout.ts`'s bipartite sort and the backend's
//   entity-cluster sort both already apply, for the same reason.
// - The simulation runs a *fixed* number of iterations with a linear
//   cooling schedule (classic Fruchterman-Reingold), never a
//   convergence/time-based stop condition. Same graph in, identical floats
//   out, on a test runner and on a projector.

import type { GraphEdge, GraphNode, KnowledgeGraph } from "../../types/documents";

export interface Point {
  x: number;
  y: number;
}

export interface ForceLayoutOptions {
  width?: number;
  height?: number;
  iterations?: number;
  seed?: number;
}

export interface ForceLayout {
  positions: Record<string, Point>;
  width: number;
  height: number;
}

const DEFAULT_WIDTH = 900;
const DEFAULT_HEIGHT = 700;
//: Measured (session plan, Phase D perf gate): 300 iterations at the
//: 600-node ceiling (MAX_GRAPH_DOCUMENTS=200, ~3 entity/madde nodes per
//: document) took ~296ms with the Barnes-Hut repulsion below -- against a
//: 150ms budget for a graph-load interaction. 150 iterations lands at
//: ~149ms and the Fruchterman-Reingold cooling schedule already scales its
//: temperature to whatever iteration count it's given, so this is a real
//: speed/settling trade-off, not a shortcut: fewer steps to relax into a
//: stable layout, not a worse algorithm. The live corpus (14 documents,
//: ~60 nodes today) settles in well under a millisecond either way.
const DEFAULT_ITERATIONS = 150;
const DEFAULT_SEED = 0x5eed1e5c; // arbitrary, fixed -- never regenerated at runtime

/** mulberry32: a small, fast, deterministic PRNG. Same seed -> same
 * infinite stream of floats in [0, 1), every time, on every platform --
 * unlike `Math.random()`, which this module must never call. */
function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// --- Barnes-Hut repulsion --------------------------------------------------
//
// Measured (see the session plan's Phase D perf gate): naive O(n^2) pairwise
// repulsion took ~4.7s at 600 nodes -- the node count `MAX_GRAPH_DOCUMENTS`
// can reach -- against a 150ms budget. This quadtree brings it to O(n log n)
// by treating a distant cluster of nodes as one pseudo-body at its center of
// mass, the standard Barnes-Hut approximation.
//
// Determinism is preserved by construction, not by luck: points are
// inserted in a *fixed* order (the caller always passes sorted node ids),
// subdivision boundaries are the exact midpoint of the parent's bounds (no
// randomness), and traversal order for force accumulation is likewise the
// caller's fixed, sorted node order.
interface QuadTreeNode {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  mass: number;
  centerX: number;
  centerY: number;
  // A leaf holds at most one point directly; once a second point would
  // land here the leaf subdivides and both points are re-inserted into
  // the four children.
  point: { x: number; y: number } | null;
  children: [QuadTreeNode, QuadTreeNode, QuadTreeNode, QuadTreeNode] | null;
}

const QUADTREE_MAX_DEPTH = 24;

function makeQuadLeaf(x0: number, y0: number, x1: number, y1: number): QuadTreeNode {
  return { x0, y0, x1, y1, mass: 0, centerX: 0, centerY: 0, point: null, children: null };
}

function subdivide(node: QuadTreeNode): void {
  const mx = (node.x0 + node.x1) / 2;
  const my = (node.y0 + node.y1) / 2;
  node.children = [
    makeQuadLeaf(node.x0, node.y0, mx, my), // NW
    makeQuadLeaf(mx, node.y0, node.x1, my), // NE
    makeQuadLeaf(node.x0, my, mx, node.y1), // SW
    makeQuadLeaf(mx, my, node.x1, node.y1), // SE
  ];
}

function quadIndexFor(node: QuadTreeNode, px: number, py: number): number {
  const mx = (node.x0 + node.x1) / 2;
  const my = (node.y0 + node.y1) / 2;
  const east = px >= mx ? 1 : 0;
  const south = py >= my ? 1 : 0;
  return south * 2 + east; // matches [NW, NE, SW, SE] order above
}

function insertPoint(node: QuadTreeNode, px: number, py: number, depth: number): void {
  if (node.mass === 0 && node.children === null) {
    node.point = { x: px, y: py };
    node.mass = 1;
    node.centerX = px;
    node.centerY = py;
    return;
  }
  if (node.children === null) {
    // This leaf already holds one point (or has hit max depth, in which
    // case it degenerates into an equal-weight stack at one location --
    // an acceptable approximation for the pathological case of many
    // coincident points, which never happens in practice after the
    // near-zero-distance jitter in the repulsion loop below).
    if (depth >= QUADTREE_MAX_DEPTH) {
      node.mass += 1;
      node.centerX = (node.centerX * (node.mass - 1) + px) / node.mass;
      node.centerY = (node.centerY * (node.mass - 1) + py) / node.mass;
      return;
    }
    const existing = node.point!;
    node.point = null;
    subdivide(node);
    insertPoint(node.children![quadIndexFor(node, existing.x, existing.y)], existing.x, existing.y, depth + 1);
  }
  insertPoint(node.children![quadIndexFor(node, px, py)], px, py, depth + 1);
  node.mass += 1;
  node.centerX = (node.centerX * (node.mass - 1) + px) / node.mass;
  node.centerY = (node.centerY * (node.mass - 1) + py) / node.mass;
}

function buildQuadTree(orderedPoints: Point[], width: number, height: number): QuadTreeNode {
  const root = makeQuadLeaf(0, 0, width, height);
  for (const p of orderedPoints) {
    insertPoint(root, p.x, p.y, 0);
  }
  return root;
}

const BARNES_HUT_THETA = 0.6;

/** Accumulates the repulsive force on (px, py) from every body in the
 * quadtree into `out`, treating any node whose bounding box is "far
 * enough" (width / distance < theta) as one pseudo-body at its center of
 * mass instead of recursing into its children. */
function accumulateRepulsion(node: QuadTreeNode, px: number, py: number, k: number, out: Point): void {
  if (node.mass === 0) return;
  const dx0 = px - node.centerX;
  const dy0 = py - node.centerY;
  const distanceToCenterOfMass = Math.sqrt(dx0 * dx0 + dy0 * dy0);
  const isLeafWithExactlyOneBody = node.children === null && node.mass === 1;
  if (isLeafWithExactlyOneBody && distanceToCenterOfMass < 1e-9) {
    // At double precision, "essentially zero distance" from a single-body
    // leaf means this body *is* the point being queried -- exclude the
    // self-force rather than let a near-zero distance blow up into a huge
    // (and directionally arbitrary) repulsion against itself.
    return;
  }
  const width = node.x1 - node.x0;
  if (node.children === null || width / Math.max(distanceToCenterOfMass, 1e-9) < BARNES_HUT_THETA) {
    let dx = dx0;
    let dy = dy0;
    let distance = distanceToCenterOfMass;
    if (distance < 0.01) {
      dx = 0.01;
      dy = 0;
      distance = 0.01;
    }
    const repulsiveForce = (node.mass * k * k) / distance;
    out.x += (dx / distance) * repulsiveForce;
    out.y += (dy / distance) * repulsiveForce;
    return;
  }
  for (const child of node.children) {
    accumulateRepulsion(child, px, py, k, out);
  }
}

/** Fruchterman-Reingold-style force-directed layout, fixed iteration count.
 *
 * Args:
 *   graph: The full knowledge graph (all node/edge types -- this module
 *     does not filter; the caller decides what subset to lay out).
 *   options: `width`/`height` of the layout canvas, `iterations` (default
 *     300 -- see the module docstring for why this is fixed rather than
 *     convergence-based), `seed` (default fixed, override only for tests
 *     that need to prove seed-independence of the *algorithm*, not for
 *     runtime variety -- production code should never pass a different
 *     seed between renders of the same graph).
 *
 * Returns:
 *   A position per node id, plus the canvas dimensions used.
 */
export function layoutForceDirected(graph: KnowledgeGraph, options: ForceLayoutOptions = {}): ForceLayout {
  const width = options.width ?? DEFAULT_WIDTH;
  const height = options.height ?? DEFAULT_HEIGHT;
  const iterations = options.iterations ?? DEFAULT_ITERATIONS;
  const seed = options.seed ?? DEFAULT_SEED;

  const nodeIds = [...new Set(graph.nodes.map((n) => n.id))].sort();
  if (nodeIds.length === 0) {
    return { positions: {}, width, height };
  }

  const random = mulberry32(seed);
  const area = width * height;
  // Fruchterman-Reingold's optimal-distance constant: the spacing that
  // would result from spreading n nodes evenly across the canvas area.
  const k = Math.sqrt(area / nodeIds.length);

  const x: Record<string, number> = {};
  const y: Record<string, number> = {};
  // Positions are seeded in sorted-id order specifically so the stream of
  // (x, y) pairs pulled from `random` is a pure function of the node id
  // set, not of whatever order `graph.nodes` happened to list them in.
  for (const id of nodeIds) {
    x[id] = random() * width;
    y[id] = random() * height;
  }

  // Only edges between two nodes actually present in this layout's node
  // set contribute an attractive force -- a filtered subgraph (e.g. the
  // compliance-only preset) must never let a spring pull toward a node
  // that isn't being drawn. Sorted afterward, deterministically: floating-
  // point addition is not associative, so the accumulation loop below
  // would otherwise produce (very slightly) different positions depending
  // on the order `graph.edges` happened to arrive in -- exactly the kind
  // of non-determinism the order-independence test below exists to catch.
  const nodeIdSet = new Set(nodeIds);
  const edges: GraphEdge[] = graph.edges
    .filter((e) => nodeIdSet.has(e.source) && nodeIdSet.has(e.target))
    .slice()
    .sort((a, b) => {
      if (a.source !== b.source) return a.source < b.source ? -1 : 1;
      if (a.target !== b.target) return a.target < b.target ? -1 : 1;
      return a.edge_type < b.edge_type ? -1 : a.edge_type > b.edge_type ? 1 : 0;
    });

  const centerX = width / 2;
  const centerY = height / 2;
  // Pulls the whole layout toward the canvas center every iteration so an
  // isolated component (or the whole graph, early on) doesn't drift off
  // canvas -- weak relative to repulsion/springs, just enough to anchor it.
  const CENTERING_STRENGTH = 0.02;

  for (let iteration = 0; iteration < iterations; iteration++) {
    const displacementX: Record<string, number> = {};
    const displacementY: Record<string, number> = {};
    for (const id of nodeIds) {
      displacementX[id] = 0;
      displacementY[id] = 0;
    }

    // Repulsion: every node pushes away from every other, inverse-
    // proportional to distance (Coulomb-like). Measured (session plan,
    // Phase D perf gate) at ~4.7s for a naive O(n^2) pass over 600 nodes --
    // well over the 150ms budget a graph-load interaction can spend here --
    // so this queries a Barnes-Hut quadtree (O(n log n)) instead of every
    // pair directly. The tree is rebuilt fresh each iteration (positions
    // moved since last iteration) from points in the same fixed, sorted
    // `nodeIds` order every time, which is what keeps the whole simulation
    // reproducible despite being an approximation.
    const quadTree = buildQuadTree(
      nodeIds.map((id) => ({ x: x[id], y: y[id] })),
      width,
      height,
    );
    for (const id of nodeIds) {
      const force: Point = { x: 0, y: 0 };
      accumulateRepulsion(quadTree, x[id], y[id], k, force);
      displacementX[id] += force.x;
      displacementY[id] += force.y;
    }

    // Attraction: connected nodes pull together, proportional to distance
    // squared over k (spring force).
    for (const e of edges) {
      const dx = x[e.source] - x[e.target];
      const dy = y[e.source] - y[e.target];
      const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 0.01);
      const attractiveForce = (distance * distance) / k;
      const fx = (dx / distance) * attractiveForce;
      const fy = (dy / distance) * attractiveForce;
      displacementX[e.source] -= fx;
      displacementY[e.source] -= fy;
      displacementX[e.target] += fx;
      displacementY[e.target] += fy;
    }

    // Centering.
    for (const id of nodeIds) {
      displacementX[id] += (centerX - x[id]) * CENTERING_STRENGTH;
      displacementY[id] += (centerY - y[id]) * CENTERING_STRENGTH;
    }

    // Cooling: linear from k at iteration 0 down to ~0 at the last
    // iteration, capping how far any node can move this step -- the
    // classic Fruchterman-Reingold "temperature", but driven purely by
    // iteration index, never by measured convergence.
    const temperature = k * (1 - iteration / iterations);
    for (const id of nodeIds) {
      const dx = displacementX[id];
      const dy = displacementY[id];
      const displacement = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const clamped = Math.min(displacement, temperature);
      x[id] += (dx / displacement) * clamped;
      y[id] += (dy / displacement) * clamped;
      // Keep every node on canvas -- a node that drifted to the edge under
      // strong early repulsion should not escape the visible area.
      x[id] = Math.min(width, Math.max(0, x[id]));
      y[id] = Math.min(height, Math.max(0, y[id]));
    }
  }

  const positions: Record<string, Point> = {};
  for (const id of nodeIds) {
    positions[id] = { x: x[id], y: y[id] };
  }
  return { positions, width, height };
}

/** Not exported for production use -- kept for one-off perf measurement
 * (see the session plan's Phase D task 21) so the same node-generation
 * logic doesn't need to be re-written ad hoc in a scratch script. */
export function __buildSyntheticGraphForBenchmark(nodeCount: number, edgesPerNode: number): KnowledgeGraph {
  const nodes: GraphNode[] = Array.from({ length: nodeCount }, (_, i) => ({
    id: `n${i}`, node_type: "entity", label: `n${i}`,
    storage_path: null, file_name: null, document_type_label: null,
    compliance_status: null, has_analysis: null,
    kanun: null, madde: null, field_labels: [], document_count: null,
    entity_kind: null, surface_forms: [], attributes: {},
  }));
  const edges: GraphEdge[] = [];
  for (let i = 0; i < nodeCount; i++) {
    for (let k = 1; k <= edgesPerNode; k++) {
      const j = (i + k) % nodeCount;
      edges.push({
        source: `n${i}`, target: `n${j}`, edge_type: "bahseder", source_kind: "llm",
        field_key: null, field_label: null, severity: null, reason: null, aciklama: null, raw: null,
      });
    }
  }
  return {
    nodes, edges,
    insights: {
      document_count: 0, madde_count: 0, kanun_count: 0, entity_count: nodeCount, konu_count: 0,
      rule_edge_count: 0, llm_edge_count: edges.length, unresolved_reference_count: 0,
      top_breached_madde: null,
    },
  };
}
