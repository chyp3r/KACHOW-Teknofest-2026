// Force-directed layout for the unified entity graph -- no React, no DOM.
//
// The v1 graph used a two-column bipartite layout because the data was
// genuinely bipartite (Document -> Madde/Kanun only). v2 adds Entity/Konu
// nodes and Document<->Entity<->Document paths, which is a general graph
// shape a bipartite layout cannot represent -- force-directed is the right
// tool here.
//
// This module has two layers, sharing one physics core:
//
// - `createForceSimulation` -- a *live*, steppable, draggable simulation
//   (`features/graph/useForceSimulation.ts` drives it via
//   requestAnimationFrame). Nodes can be pinned (drag-and-drop, csacademy-
//   style) and the graph can be reheated (a filter change, a new drag) --
//   both are fundamentally stateful, so this layer does not promise
//   frame-by-frame reproducibility. What it does promise: given the same
//   seed and the same graph, the *initial* placement and the *settled*
//   configuration (after `isSettled()` with no interaction) are
//   reproducible. A user drag intentionally diverges from the unattended
//   result -- that divergence is the point of dragging.
// - `layoutForceDirected` -- a thin batch wrapper: create a simulation, step
//   it a fixed number of times, return the result. This is the layer that
//   keeps the older, stronger guarantee (same graph in, identical floats
//   out) and is what the reduced-motion path and every determinism test
//   below exercise.
//
// Both layers avoid `Math.random()` -- initial positions come from a seeded
// PRNG (mulberry32) consumed in *sorted node-id order*, so the output never
// depends on the order nodes/edges arrive in (the same discipline
// `layout.ts`'s bipartite sort and the backend's entity-cluster sort both
// already apply, for the same reason).

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

//: Exported so a caller sizing its viewport (EntityGraphView's
//: InteractiveGraphViewport baseWidth/baseHeight) uses the exact canvas
//: the simulation itself lays out on, rather than a second, potentially
//: drifting copy of the same numbers.
export const DEFAULT_WIDTH = 900;
export const DEFAULT_HEIGHT = 700;
//: Measured (session plan, Phase D perf gate): 300 iterations at the
//: 600-node ceiling (MAX_GRAPH_DOCUMENTS=200, ~3 entity/madde nodes per
//: document) took ~296ms with the Barnes-Hut repulsion below -- against a
//: 150ms budget for a graph-load interaction. 150 iterations lands at
//: ~149ms, and the alpha cooling schedule below scales to whatever
//: iteration count it's given, so this is a real speed/settling trade-off,
//: not a shortcut: fewer steps to relax into a stable layout, not a worse
//: algorithm. The live corpus (14 documents, ~60 nodes today) settles in
//: well under a millisecond either way.
const DEFAULT_ITERATIONS = 150;
const DEFAULT_SEED = 0x5eed1e5c; // arbitrary, fixed -- never regenerated at runtime

//: Below this, a node's displacement this step is small enough to call the
//: simulation settled -- the live loop stops scheduling frames, and the
//: batch path's cooling reaches (approximately) zero. d3-force's own
//: default; there is nothing project-specific about this number.
const ALPHA_MIN = 0.001;
//: Derived so that, left un-reheated, alpha decays from 1 to ALPHA_MIN in
//: almost exactly DEFAULT_ITERATIONS steps -- the live loop settles on
//: roughly the same timescale the batch path was measured and tuned at,
//: rather than an arbitrarily different one.
const DEFAULT_ALPHA_DECAY = 1 - Math.pow(ALPHA_MIN, 1 / DEFAULT_ITERATIONS);
//: `reheat()`'s default target when the caller doesn't specify one (a
//: filter toggle, e.g.) -- enough to visibly re-settle the affected part of
//: the graph without the full graph re-scrambling the way a fresh alpha=1
//: restart would (see the session plan's "reheating on every filter
//: toggle" risk note).
const DEFAULT_REHEAT_ALPHA = 0.3;

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

export interface ForceSimulationOptions {
  width?: number;
  height?: number;
  seed?: number;
}

export interface ForceSimulation {
  /** Mutated in place every `step()` -- the same `Point` object identity
   * persists for a node's whole lifetime in the simulation, so a consumer
   * that re-renders on some other signal (a tick counter, say) always
   * reads current coordinates without needing new object identities. */
  positions: Record<string, Point>;
  width: number;
  height: number;
  /** The cooling temperature, 1 (freshly seeded or just reheated) down to
   * ALPHA_MIN (settled). Read-only from the outside; `step()`/`reheat()`
   * are the only things that change it. */
  readonly alpha: number;
  /** Advance the simulation by exactly one tick: repulsion, attraction,
   * centering, then move every unpinned node by its clamped, alpha-scaled
   * displacement. Pinned nodes still exert forces on everything else; they
   * just never move themselves. */
  step(): void;
  /** True once `alpha` has decayed to ALPHA_MIN -- the live loop
   * (`useForceSimulation`) stops scheduling frames when this flips. */
  isSettled(): boolean;
  /** Raise alpha back up so the simulation visibly relaxes again --
   * called on drag start and on a filter change. Never lowers alpha (a
   * reheat mid-cooldown should not un-settle a graph that was already
   * calmer than the target). */
  reheat(target?: number): void;
  /** Fix a node at an exact position -- what dragging does every pointer-
   * move, and what "the node becomes fixed" (csacademy's own wording) does
   * on drop, since pinning persists after the pointer is released. */
  pin(id: string, x: number, y: number): void;
  unpin(id: string): void;
  isPinned(id: string): boolean;
  /** Replace the working graph (e.g. a filter toggle) while preserving the
   * position of every node id that survives -- a full re-seed would make
   * the whole layout visibly jump on every filter click. Node ids that are
   * new are seeded from the same PRNG stream, in sorted-id order among
   * just the new ids, so seeding stays a pure function of *which* ids are
   * new, not of how many `syncGraph` calls preceded this one. Node ids
   * that are gone lose their position and pinned state. */
  syncGraph(graph: KnowledgeGraph): void;
}

// Pulls the whole layout toward the canvas center every step so an isolated
// component (or the whole graph, early on) doesn't drift off canvas --
// weak relative to repulsion/springs, just enough to anchor it.
const CENTERING_STRENGTH = 0.02;

function sortedEdgesWithin(edges: GraphEdge[], nodeIdSet: Set<string>): GraphEdge[] {
  // Only edges between two nodes actually present in the current node set
  // contribute an attractive force -- a filtered subgraph (e.g. the
  // compliance-only preset) must never let a spring pull toward a node
  // that isn't being drawn. Sorted afterward, deterministically: floating-
  // point addition is not associative, so the accumulation loop would
  // otherwise produce (very slightly) different positions depending on the
  // order `graph.edges` happened to arrive in.
  return edges
    .filter((e) => nodeIdSet.has(e.source) && nodeIdSet.has(e.target))
    .slice()
    .sort((a, b) => {
      if (a.source !== b.source) return a.source < b.source ? -1 : 1;
      if (a.target !== b.target) return a.target < b.target ? -1 : 1;
      return a.edge_type < b.edge_type ? -1 : a.edge_type > b.edge_type ? 1 : 0;
    });
}

/** The live, steppable, pinnable, reheatable simulation core -- see the
 * module docstring for the reproducibility contract this layer keeps
 * (initial and settled states, not every intermediate frame). */
export function createForceSimulation(
  graph: KnowledgeGraph,
  options: ForceSimulationOptions = {},
): ForceSimulation {
  const width = options.width ?? DEFAULT_WIDTH;
  const height = options.height ?? DEFAULT_HEIGHT;
  const seed = options.seed ?? DEFAULT_SEED;
  const centerX = width / 2;
  const centerY = height / 2;

  const random = mulberry32(seed);
  const positions: Record<string, Point> = {};
  const pinned = new Set<string>();
  let nodeIds: string[] = [];
  let edges: GraphEdge[] = [];
  let k = 1;
  let alpha = 1;

  function seedPosition(id: string): void {
    // Positions are seeded in sorted-id order specifically so the stream
    // of (x, y) pairs pulled from `random` is a pure function of the node
    // id set, not of whatever order `graph.nodes` happened to list them
    // in -- see the "is independent of input order" test below.
    positions[id] = { x: random() * width, y: random() * height };
  }

  function applyGraph(nextGraph: KnowledgeGraph): void {
    const nextIds = [...new Set(nextGraph.nodes.map((n) => n.id))].sort();
    const nextIdSet = new Set(nextIds);

    for (const id of nodeIds) {
      if (!nextIdSet.has(id)) {
        delete positions[id];
        pinned.delete(id);
      }
    }
    for (const id of nextIds) {
      if (!(id in positions)) seedPosition(id);
    }

    nodeIds = nextIds;
    edges = sortedEdgesWithin(nextGraph.edges, nextIdSet);
    // Fruchterman-Reingold's optimal-distance constant: the spacing that
    // would result from spreading n nodes evenly across the canvas area.
    // Recomputed on every graph change so it always reflects the current
    // node count, the same way the original batch function computed it
    // once from the graph it was given.
    k = nodeIds.length > 0 ? Math.sqrt((width * height) / nodeIds.length) : 1;
  }

  applyGraph(graph);

  function step(): void {
    const displacementX: Record<string, number> = {};
    const displacementY: Record<string, number> = {};
    for (const id of nodeIds) {
      displacementX[id] = 0;
      displacementY[id] = 0;
    }

    // Repulsion via Barnes-Hut (see the section above) -- rebuilt fresh
    // every step from the current, sorted node order.
    const quadTree = buildQuadTree(
      nodeIds.map((id) => positions[id]),
      width,
      height,
    );
    for (const id of nodeIds) {
      const force: Point = { x: 0, y: 0 };
      accumulateRepulsion(quadTree, positions[id].x, positions[id].y, k, force);
      displacementX[id] += force.x;
      displacementY[id] += force.y;
    }

    // Attraction: connected nodes pull together, proportional to distance
    // squared over k (spring force). A pinned node still receives and
    // contributes attraction/repulsion -- only its own displacement is
    // discarded below.
    for (const e of edges) {
      const dx = positions[e.source].x - positions[e.target].x;
      const dy = positions[e.source].y - positions[e.target].y;
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
      displacementX[id] += (centerX - positions[id].x) * CENTERING_STRENGTH;
      displacementY[id] += (centerY - positions[id].y) * CENTERING_STRENGTH;
    }

    // Cooling: alpha-scaled temperature caps how far any node can move
    // this step -- the classic Fruchterman-Reingold "temperature", but
    // driven by a decaying alpha rather than a fixed iteration count, so
    // it works whether this step is the 1st of a fixed batch of 150 or an
    // arbitrary tick of a live loop that might be reheated at any moment.
    const temperature = k * alpha;
    for (const id of nodeIds) {
      if (pinned.has(id)) continue;
      const dx = displacementX[id];
      const dy = displacementY[id];
      const displacement = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const clamped = Math.min(displacement, temperature);
      const point = positions[id];
      point.x += (dx / displacement) * clamped;
      point.y += (dy / displacement) * clamped;
      // Keep every node on canvas -- a node that drifted to the edge under
      // strong early repulsion should not escape the visible area.
      point.x = Math.min(width, Math.max(0, point.x));
      point.y = Math.min(height, Math.max(0, point.y));
    }

    alpha = Math.max(ALPHA_MIN, alpha * (1 - DEFAULT_ALPHA_DECAY));
  }

  return {
    positions,
    width,
    height,
    get alpha() {
      return alpha;
    },
    step,
    isSettled: () => alpha <= ALPHA_MIN,
    reheat: (target = DEFAULT_REHEAT_ALPHA) => {
      alpha = Math.max(alpha, target);
    },
    pin: (id, px, py) => {
      pinned.add(id);
      if (!positions[id]) positions[id] = { x: px, y: py };
      else {
        positions[id].x = px;
        positions[id].y = py;
      }
    },
    unpin: (id) => {
      pinned.delete(id);
    },
    isPinned: (id) => pinned.has(id),
    syncGraph: applyGraph,
  };
}

/** Fruchterman-Reingold-style force-directed layout, fixed iteration count.
 * A thin wrapper over `createForceSimulation` -- see the module docstring
 * for why this layer, unlike the live simulation, keeps the stronger
 * "identical floats out" guarantee.
 *
 * Args:
 *   graph: The full knowledge graph (all node/edge types -- this module
 *     does not filter; the caller decides what subset to lay out).
 *   options: `width`/`height` of the layout canvas, `iterations` (default
 *     150 -- see the constant above for the measurement behind it),
 *     `seed` (default fixed, override only for tests that need to prove
 *     seed-independence of the *algorithm*, not for runtime variety --
 *     production code should never pass a different seed between renders
 *     of the same graph).
 *
 * Returns:
 *   A position per node id, plus the canvas dimensions used.
 */
export function layoutForceDirected(graph: KnowledgeGraph, options: ForceLayoutOptions = {}): ForceLayout {
  const iterations = options.iterations ?? DEFAULT_ITERATIONS;
  const simulation = createForceSimulation(graph, options);
  for (let i = 0; i < iterations; i++) {
    simulation.step();
  }
  // Snapshot: `simulation.positions` is a live, mutable object owned by the
  // simulation (which this function discards on return) -- copying it out
  // means the caller's result can't be affected by a simulation instance
  // it never gets a reference to.
  const positions: Record<string, Point> = {};
  for (const [id, point] of Object.entries(simulation.positions)) {
    positions[id] = { x: point.x, y: point.y };
  }
  return { positions, width: simulation.width, height: simulation.height };
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
