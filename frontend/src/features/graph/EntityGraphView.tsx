import { Network } from "lucide-react";
import { useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { InteractiveGraphViewport } from "../../components/InteractiveGraphViewport";
import { useGraphViewport, type Point } from "../../components/graphViewportContext";
import { Card, Spinner } from "../../components/Surface";
import { EmptyState } from "../../components/EmptyState";
import type { GraphEdge, GraphNode, KnowledgeGraph } from "../../types/documents";
import { graphCanvasSize } from "./canvasSize";
import { COMPLIANCE_ONLY_EDGE_TYPES, COMPLIANCE_ONLY_NODE_TYPES, filterGraph, filterToComplianceOnly } from "./filters";
import { GraphFilters } from "./GraphFilters";
import { KnowledgeGraphView } from "./KnowledgeGraphView";
import { NodeInspector } from "./NodeInspector";
import { useForceSimulation } from "./useForceSimulation";

const NODE_RADIUS: Record<GraphNode["node_type"], number> = {
  document: 10,
  entity: 8,
  madde: 9,
  kanun: 12,
  konu: 7,
};

// Konu is off by default -- measured weaker signal (24 doc-pairs against
// muhatap's 45 and entities' 81, see the session plan's measurement table)
// and starting with it hidden keeps the first render legible.
const DEFAULT_NODE_TYPES = new Set<GraphNode["node_type"]>(["document", "entity", "madde", "kanun"]);
const DEFAULT_EDGE_TYPES = new Set<GraphEdge["edge_type"]>([
  "ihlal", "atif", "muhatap", "gonderen", "bahseder", "konu",
]);

// A pointer that moved less than this, end to end, is a click (open the
// inspector) rather than a drag (pin the node) -- csacademy's own
// distinction between "click fixes/unfixes" and "drag and drop", adapted
// to this app's choice of click-opens-attributes instead.
const CLICK_MOVE_THRESHOLD_PX = 3;


function isIncident(nodeId: string, hoveredId: string | null, edges: GraphEdge[]): boolean {
  if (!hoveredId) return true;
  if (nodeId === hoveredId) return true;
  return edges.some(
    (edge) =>
      (edge.source === hoveredId && edge.target === nodeId) ||
      (edge.target === hoveredId && edge.source === nodeId),
  );
}

/** One draggable, clickable node. Split out of `EntityGraphView` because
 * `useGraphViewport()` reads React context by fiber position, not by JSX
 * text nesting -- a hook call inside `EntityGraphView`'s own `.map()`
 * would still run in *`EntityGraphView`'s* render, which sits above
 * `InteractiveGraphViewport`'s context provider, not below it. Only a
 * component actually instantiated as that provider's descendant (which
 * this one is, once rendered as a child of `InteractiveGraphViewport`)
 * sees the context. */
function EntityGraphNode({
  node,
  position,
  incident,
  pinned,
  onHover,
  onUnhover,
  onSelect,
  onPin,
  onUnpin,
}: {
  node: GraphNode;
  position: Point;
  incident: boolean;
  pinned: boolean;
  onHover: () => void;
  onUnhover: () => void;
  onSelect: () => void;
  onPin: (x: number, y: number) => void;
  onUnpin: () => void;
}) {
  const { graphPointAt } = useGraphViewport();
  const dragRef = useRef<{ startX: number; startY: number; moved: boolean } | null>(null);
  const radius = NODE_RADIUS[node.node_type];

  const handlePointerDown = (event: ReactPointerEvent<SVGGElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = { startX: event.clientX, startY: event.clientY, moved: false };
  };

  const handlePointerMove = (event: ReactPointerEvent<SVGGElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    // Below the click tolerance, don't pin at all -- a pin here would
    // leave the node stuck in place after what the user experiences as
    // "just a click", not a drag.
    if (!drag.moved && Math.hypot(dx, dy) <= CLICK_MOVE_THRESHOLD_PX) return;
    drag.moved = true;
    const point = graphPointAt({ x: event.clientX, y: event.clientY });
    onPin(point.x, point.y);
  };

  const handlePointerUp = (event: ReactPointerEvent<SVGGElement>) => {
    const drag = dragRef.current;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    dragRef.current = null;
    // csacademy's own wording: "at the end of the drop the node becomes
    // fixed" -- a real drag (drag.moved) leaves the node pinned exactly
    // where it was released; only a plain click (no movement) opens the
    // inspector instead.
    if (drag && !drag.moved) onSelect();
  };

  const handleKeyDown = (event: ReactKeyboardEvent<SVGGElement>) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onSelect();
  };

  return (
    <g
      className={`entity-graph-node node-${node.node_type} ${pinned ? "is-pinned" : ""} ${
        incident ? "" : "is-dimmed"
      }`.trim()}
      data-node-id={node.id}
      data-graph-node=""
      role="button"
      tabIndex={0}
      aria-label={node.label}
      onMouseEnter={onHover}
      onMouseLeave={onUnhover}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onDoubleClick={onUnpin}
      onKeyDown={handleKeyDown}
    >
      <circle
        cx={position.x}
        cy={position.y}
        r={radius}
        className={`entity-graph-node-fill status-${node.compliance_status ?? "unknown"}`}
      />
      <text x={position.x + radius + 4} y={position.y + 4} className="node-label">
        {node.label}
      </text>
    </g>
  );
}

/** The force simulation + interactive viewport + node inspector for the
 * unified graph. Split out of `EntityGraphView` so it can be remounted (via
 * `key`) when `graphCanvasSize` returns a different canvas: `useForceSimulation`
 * reads its `width`/`height` once, at creation, so a resize only takes effect
 * on a fresh mount. Selection/hover live in the parent and survive the
 * remount; only the transient pin positions reset, which a node-count change
 * (always a filter toggle) reheats anyway. */
function EntityGraphCanvas({
  filtered,
  width,
  height,
  hoveredId,
  onHoverNode,
  onSelectNode,
  selectedNode,
  onCloseInspector,
  onSelectDocument,
}: {
  filtered: KnowledgeGraph;
  width: number;
  height: number;
  hoveredId: string | null;
  onHoverNode: (id: string | null) => void;
  onSelectNode: (id: string | null) => void;
  selectedNode: GraphNode | null;
  onCloseInspector: () => void;
  onSelectDocument?: (storagePath: string) => void;
}) {
  const { positions, pin, unpin, isPinned } = useForceSimulation(filtered, {
    width,
    height,
  });

  return (
    <>
      <InteractiveGraphViewport
        ariaLabel="Etkileşimli uyum ve varlık haritası"
        baseWidth={width}
        baseHeight={height}
      >
        {filtered.edges.map((edge, index) => {
          const from = positions[edge.source];
          const to = positions[edge.target];
          if (!from || !to) return null;
          const incident =
            !hoveredId || edge.source === hoveredId || edge.target === hoveredId;
          const kind = edge.source_kind === "rule" ? "edge-rule" : "edge-llm";
          return (
            <line
              key={`${edge.source}->${edge.target}#${index}`}
              className={`entity-graph-edge ${kind} ${incident ? "" : "is-dimmed"}`.trim()}
              data-edge-type={edge.edge_type}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
            />
          );
        })}

        {filtered.nodes.map((node) => {
          const position = positions[node.id];
          if (!position) return null;
          return (
            <EntityGraphNode
              key={node.id}
              node={node}
              position={position}
              incident={isIncident(node.id, hoveredId, filtered.edges)}
              pinned={isPinned(node.id)}
              onHover={() => onHoverNode(node.id)}
              onUnhover={() => onHoverNode(null)}
              onSelect={() => onSelectNode(node.id)}
              onPin={(x, y) => pin(node.id, x, y)}
              onUnpin={() => unpin(node.id)}
            />
          );
        })}
      </InteractiveGraphViewport>

      <NodeInspector
        node={selectedNode}
        onClose={onCloseInspector}
        onOpenDocument={onSelectDocument}
        pinned={selectedNode ? isPinned(selectedNode.id) : false}
        onUnpin={selectedNode ? () => unpin(selectedNode.id) : undefined}
      />
    </>
  );
}

/** The unified graph: every node type in one live, draggable force
 * simulation (`useForceSimulation` -- csacademy-style: nodes settle, then
 * sleep; dragging wakes and pins), with a click-to-inspect floating panel
 * and a filter panel that includes a "compliance-only" preset reproducing
 * exactly the bipartite view PR #212 shipped (via `filterToComplianceOnly`
 * + the unchanged `KnowledgeGraphView` -- not a re-implementation). See
 * the session plan for why entity nodes are sourced from `entities[]`/
 * `muhatap`/`gonderen_kurum` rather than `imza_sahibi` (empty on every
 * real document in this corpus). */
export function EntityGraphView({
  graph,
  loading = false,
  onSelectDocument,
}: {
  graph: KnowledgeGraph | null;
  loading?: boolean;
  onSelectDocument?: (storagePath: string) => void;
}) {
  const [mode, setMode] = useState<"unified" | "compliance">("unified");
  const [nodeTypes, setNodeTypes] = useState<Set<GraphNode["node_type"]>>(DEFAULT_NODE_TYPES);
  const [edgeTypes, setEdgeTypes] = useState<Set<GraphEdge["edge_type"]>>(DEFAULT_EDGE_TYPES);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const filtered = useMemo(
    () => (graph ? filterGraph(graph, { nodeTypes, edgeTypes }) : null),
    [graph, nodeTypes, edgeTypes],
  );
  // Canvas grows with the number of nodes actually on screen (post-filter).
  const canvas = useMemo(
    () => graphCanvasSize(filtered?.nodes.length ?? 0),
    [filtered?.nodes.length],
  );

  const toggleSet = <T,>(set: Set<T>, value: T): Set<T> => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    return next;
  };

  if (loading) {
    return (
      <Card className="knowledge-graph-loading">
        <Spinner label="Mevzuat haritası yükleniyor" size="lg" />
      </Card>
    );
  }

  if (!graph || graph.nodes.length === 0) {
    return (
      <EmptyState
        icon={Network}
        title="Henüz evrak yok"
        description="Uyum haritası, analiz edilmiş evraklar yüklendiğinde burada oluşacak."
      />
    );
  }

  const filterPanel = (
    <GraphFilters
      mode={mode}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onToggleNodeType={(type) => setNodeTypes((current) => toggleSet(current, type))}
      onToggleEdgeType={(type) => setEdgeTypes((current) => toggleSet(current, type))}
      onSelectPreset={(preset) => {
        setMode(preset);
        if (preset === "compliance") {
          setNodeTypes(new Set(COMPLIANCE_ONLY_NODE_TYPES));
          setEdgeTypes(new Set(COMPLIANCE_ONLY_EDGE_TYPES));
        } else {
          setNodeTypes(new Set(DEFAULT_NODE_TYPES));
          setEdgeTypes(new Set(DEFAULT_EDGE_TYPES));
        }
        setSelectedNodeId(null);
      }}
    />
  );

  if (mode === "compliance") {
    return (
      <div className="entity-graph-view">
        {filterPanel}
        <KnowledgeGraphView
          graph={filterToComplianceOnly(graph)}
          loading={loading}
          onSelectDocument={onSelectDocument}
        />
      </div>
    );
  }

  const selectedNode = filtered?.nodes.find((n) => n.id === selectedNodeId) ?? null;

  return (
    <div className="entity-graph-view">
      {filterPanel}
      <div className="entity-graph-canvas-row">
        {filtered && (
          <EntityGraphCanvas
            key={`${canvas.width}x${canvas.height}`}
            filtered={filtered}
            width={canvas.width}
            height={canvas.height}
            hoveredId={hoveredId}
            onHoverNode={setHoveredId}
            onSelectNode={setSelectedNodeId}
            selectedNode={selectedNode}
            onCloseInspector={() => setSelectedNodeId(null)}
            onSelectDocument={onSelectDocument}
          />
        )}
      </div>
    </div>
  );
}
