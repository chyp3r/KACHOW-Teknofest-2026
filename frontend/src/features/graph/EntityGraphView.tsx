import { Network } from "lucide-react";
import { useMemo, useState, type KeyboardEvent } from "react";
import { InteractiveGraphViewport } from "../../components/InteractiveGraphViewport";
import { Card, Spinner } from "../../components/Surface";
import { EmptyState } from "../../components/EmptyState";
import type { GraphEdge, GraphNode, KnowledgeGraph } from "../../types/documents";
import { COMPLIANCE_ONLY_EDGE_TYPES, COMPLIANCE_ONLY_NODE_TYPES, filterGraph, filterToComplianceOnly } from "./filters";
import { layoutForceDirected } from "./forceLayout";
import { GraphFilters } from "./GraphFilters";
import { KnowledgeGraphView } from "./KnowledgeGraphView";
import { NodeInspector } from "./NodeInspector";

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

function isIncident(nodeId: string, hoveredId: string | null, edges: GraphEdge[]): boolean {
  if (!hoveredId) return true;
  if (nodeId === hoveredId) return true;
  return edges.some(
    (edge) =>
      (edge.source === hoveredId && edge.target === nodeId) ||
      (edge.target === hoveredId && edge.source === nodeId),
  );
}

/** The unified graph: every node type in one force-directed layout, with a
 * click-to-inspect side panel and a filter panel that includes a
 * "compliance-only" preset reproducing exactly the bipartite view PR #212
 * shipped (via `filterToComplianceOnly` + the unchanged `KnowledgeGraphView`
 * -- not a re-implementation). See the session plan for why entity nodes
 * are sourced from `entities[]`/`muhatap`/`gonderen_kurum` rather than
 * `imza_sahibi` (empty on every real document in this corpus). */
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
  const layout = useMemo(() => (filtered ? layoutForceDirected(filtered) : null), [filtered]);

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

  const selectedNode = filtered?.nodes.find((node) => node.id === selectedNodeId) ?? null;

  const handleKeyActivate = (event: KeyboardEvent<SVGGElement>, nodeId: string) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    setSelectedNodeId(nodeId);
  };

  return (
    <div className="entity-graph-view">
      {filterPanel}
      <div className="entity-graph-canvas-row">
        {layout && filtered && (
          <InteractiveGraphViewport
            ariaLabel="Etkileşimli uyum ve varlık haritası"
            baseWidth={layout.width}
            baseHeight={layout.height}
          >
            {filtered.edges.map((edge, index) => {
              const from = layout.positions[edge.source];
              const to = layout.positions[edge.target];
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
              const position = layout.positions[node.id];
              if (!position) return null;
              const incident = isIncident(node.id, hoveredId, filtered.edges);
              return (
                <g
                  key={node.id}
                  className={`entity-graph-node node-${node.node_type} ${incident ? "" : "is-dimmed"}`.trim()}
                  data-node-id={node.id}
                  role="button"
                  tabIndex={0}
                  aria-label={node.label}
                  onMouseEnter={() => setHoveredId(node.id)}
                  onMouseLeave={() => setHoveredId(null)}
                  onClick={() => setSelectedNodeId(node.id)}
                  onKeyDown={(event) => handleKeyActivate(event, node.id)}
                >
                  <circle
                    cx={position.x}
                    cy={position.y}
                    r={NODE_RADIUS[node.node_type]}
                    className={`entity-graph-node-fill status-${node.compliance_status ?? "unknown"}`}
                  />
                  <text x={position.x + NODE_RADIUS[node.node_type] + 4} y={position.y + 4} className="node-label">
                    {node.label}
                  </text>
                </g>
              );
            })}
          </InteractiveGraphViewport>
        )}

        <NodeInspector
          node={selectedNode}
          onClose={() => setSelectedNodeId(null)}
          onOpenDocument={onSelectDocument}
        />
      </div>
    </div>
  );
}
