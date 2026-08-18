import { Network } from "lucide-react";
import { useMemo, useState, type KeyboardEvent } from "react";
import { InteractiveGraphViewport } from "../../components/InteractiveGraphViewport";
import { Card } from "../../components/Surface";
import { EmptyState } from "../../components/EmptyState";
import { Spinner } from "../../components/Surface";
import type { GraphNode, KnowledgeGraph } from "../../types/documents";
import { layoutBipartite, truncateLabel } from "./layout";

const HEADER_PADDING = 12;
const NODE_HEIGHT = 16;
const DOC_NODE_WIDTH = 140;
const MADDE_NODE_MIN_WIDTH = 60;
const MADDE_NODE_MAX_WIDTH = 160;
const CANVAS_MARGIN_BOTTOM = 30;

function isIncident(node: GraphNode, hoveredId: string | null, graph: KnowledgeGraph): boolean {
  if (!hoveredId) return true;
  if (node.id === hoveredId) return true;
  return graph.edges.some(
    (edge) =>
      (edge.source === hoveredId && edge.target === node.id) ||
      (edge.target === hoveredId && edge.source === node.id),
  );
}

/** How many distinct-document breaches this madde is scaled by, for its box width. */
function maddeWidth(documentCount: number, maxCount: number): number {
  if (maxCount <= 0) return MADDE_NODE_MIN_WIDTH;
  const ratio = documentCount / maxCount;
  return MADDE_NODE_MIN_WIDTH + ratio * (MADDE_NODE_MAX_WIDTH - MADDE_NODE_MIN_WIDTH);
}

export function KnowledgeGraphView({
  graph,
  loading = false,
  onSelectDocument,
}: {
  graph: KnowledgeGraph | null;
  loading?: boolean;
  onSelectDocument?: (storagePath: string) => void;
}) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const layout = useMemo(() => (graph ? layoutBipartite(graph) : null), [graph]);

  const maxMaddeCount = useMemo(() => {
    if (!layout) return 0;
    return layout.maddeRows.reduce((max, row) => Math.max(max, row.node.document_count ?? 0), 0);
  }, [layout]);

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

  const top = graph.insights.top_breached_madde;
  const kanunLabelById = new Map(
    graph.nodes.filter((node) => node.node_type === "kanun").map((node) => [node.kanun, node.label]),
  );
  const isSingleKanun = layout ? layout.kanunBands.length <= 1 : true;

  const handleKeyActivate = (event: KeyboardEvent<SVGGElement>, node: GraphNode) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    if (node.node_type === "document" && node.storage_path) {
      onSelectDocument?.(node.storage_path);
    }
  };

  return (
    <div className="knowledge-graph-view">
      {top && (
        <Card className="knowledge-graph-headline">
          <p className="knowledge-graph-headline-text">
            <strong>
              {kanunLabelById.get(top.kanun) ?? `Kanun ${top.kanun}`} {`m.${top.madde}`}
              {top.field_labels.length > 0 ? ` (${top.field_labels.join(", ")})` : ""}
            </strong>
            {" — "}
            {graph.insights.document_count} evrakın {top.document_count}
            {"'sinde eksik."}
          </p>
          <p className="knowledge-graph-headline-note">
            Kaynak: kural tablosu — deterministik, model çıktısı değil.
          </p>
          <p className="knowledge-graph-headline-stats">
            {graph.insights.document_count} belge · {graph.insights.madde_count} madde ·{" "}
            {graph.insights.rule_edge_count + graph.insights.llm_edge_count} bağlantı (
            {graph.insights.rule_edge_count} kural, {graph.insights.llm_edge_count} model önerisi)
          </p>
        </Card>
      )}

      {isSingleKanun && layout && layout.kanunBands[0] && (
        <p className="knowledge-graph-kanun-header">{layout.kanunBands[0].node.label}</p>
      )}

      {layout && (
        <InteractiveGraphViewport
          ariaLabel="Uyum haritası: evrak ve mevzuat madde ilişkileri"
          baseWidth={layout.width}
          baseHeight={layout.height + CANVAS_MARGIN_BOTTOM}
        >
          {!isSingleKanun &&
            layout.kanunBands.map((band) => (
              <rect
                key={band.node.id}
                className="kanun-band"
                x={0}
                y={band.y - HEADER_PADDING / 2}
                width={layout.width}
                height={band.height + HEADER_PADDING}
                data-node-id={band.node.id}
              />
            ))}

          {layout.ribbons.map((ribbon, index) => {
            const incident =
              !hoveredId || ribbon.edge.source === hoveredId || ribbon.edge.target === hoveredId;
            const kind = ribbon.edge.source_kind === "rule" ? "ribbon-rule" : "ribbon-llm";
            return (
              <path
                // Edges carry no id of their own; source+target+index is stable
                // across re-renders of the same graph (layoutBipartite's output
                // order is deterministic) but distinguishes parallel edges
                // between the same two nodes (e.g. imza_sahibi + imza_unvani,
                // both doc -> madde:2646:17).
                key={`${ribbon.edge.source}->${ribbon.edge.target}#${index}`}
                className={`ribbon ${kind} ${incident ? "" : "is-dimmed"}`.trim()}
                d={ribbon.path}
                fill="none"
              />
            );
          })}

          {layout.documentRows.map((row) => {
            const incident = isIncident(row.node, hoveredId, graph);
            return (
              <g
                key={row.node.id}
                className={`node node-document ${incident ? "" : "is-dimmed"}`.trim()}
                data-node-id={row.node.id}
                role="button"
                tabIndex={0}
                aria-label={row.node.file_name ?? row.node.label}
                onMouseEnter={() => setHoveredId(row.node.id)}
                onMouseLeave={() => setHoveredId(null)}
                onClick={() => row.node.storage_path && onSelectDocument?.(row.node.storage_path)}
                onKeyDown={(event) => handleKeyActivate(event, row.node)}
              >
                <rect
                  x={row.x}
                  y={row.y - NODE_HEIGHT / 2}
                  width={DOC_NODE_WIDTH}
                  height={NODE_HEIGHT}
                  rx={4}
                  className={`node-fill status-${row.node.compliance_status ?? "unknown"} ${
                    row.node.has_analysis === false ? "no-analysis" : ""
                  }`.trim()}
                />
                <text x={row.x + 6} y={row.y + 4} className="node-label">
                  {truncateLabel(row.node.file_name ?? row.node.label, 24)}
                </text>
              </g>
            );
          })}

          {layout.maddeRows.map((row) => {
            const incident = isIncident(row.node, hoveredId, graph);
            const width = maddeWidth(row.node.document_count ?? 0, maxMaddeCount);
            return (
              <g
                key={row.node.id}
                className={`node node-madde ${incident ? "" : "is-dimmed"}`.trim()}
                data-node-id={row.node.id}
                role="button"
                tabIndex={0}
                aria-label={`${row.node.label} ${row.node.field_labels.join(", ")}`}
                onMouseEnter={() => setHoveredId(row.node.id)}
                onMouseLeave={() => setHoveredId(null)}
                onKeyDown={(event) => handleKeyActivate(event, row.node)}
              >
                <rect
                  x={row.x}
                  y={row.y - NODE_HEIGHT / 2}
                  width={width}
                  height={NODE_HEIGHT}
                  rx={4}
                  className="node-fill node-fill-madde"
                />
                <text x={row.x + 6} y={row.y + 4} className="node-label">
                  {row.node.label}
                  {row.node.field_labels.length > 0 ? ` · ${row.node.field_labels.join(", ")}` : ""}
                </text>
              </g>
            );
          })}
        </InteractiveGraphViewport>
      )}
    </div>
  );
}
