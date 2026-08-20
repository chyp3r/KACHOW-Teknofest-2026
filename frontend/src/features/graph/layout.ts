// Pure layout math for the compliance knowledge graph -- no React, no DOM.
//
// Chosen shape: a two-column bipartite ribbon diagram (documents left,
// madde/kanun right), not a force-directed layout. The data is genuinely
// bipartite (Document -> Madde/Kanun, never Document -> Document -- see the
// backend knowledge_graph module's own docstring for why), and a force
// simulation is the wrong tool for bipartite data: it settles into an
// unpredictable shape, differs run to run, and is unreadable on a static
// projector screenshot. This layout is fully deterministic -- same graph in,
// identical pixel output out -- which is also what makes it testable without
// a DOM.

import type { GraphEdge, GraphNode, KnowledgeGraph } from "../../types/documents";

export interface LayoutOptions {
  width?: number;
  rowHeight?: number;
  headerHeight?: number;
  leftX?: number;
  rightX?: number;
}

export interface DocumentRow {
  node: GraphNode;
  x: number;
  y: number;
  breachCount: number;
}

export interface MaddeRow {
  node: GraphNode;
  x: number;
  y: number;
}

export interface KanunBand {
  node: GraphNode;
  y: number;
  height: number;
}

export interface Ribbon {
  edge: GraphEdge;
  path: string;
}

export interface BipartiteLayout {
  documentRows: DocumentRow[];
  maddeRows: MaddeRow[];
  kanunBands: KanunBand[];
  ribbons: Ribbon[];
  width: number;
  height: number;
}

const DEFAULT_WIDTH = 900;
const DEFAULT_ROW_HEIGHT = 22;
const DEFAULT_HEADER_HEIGHT = 60;
const DEFAULT_LEFT_X = 40;

/** A cubic-Bézier ribbon between two row anchors, horizontal S-curve. */
export function ribbonPath(x1: number, y1: number, x2: number, y2: number): string {
  const midX = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`;
}

/** Truncates to at most `maxLength` characters, appending an ellipsis when cut. */
export function truncateLabel(label: string, maxLength: number): string {
  if (label.length <= maxLength) return label;
  return `${label.slice(0, Math.max(0, maxLength - 1))}…`;
}

function byCountDescThenIdAsc<T extends { id: string }>(count: (item: T) => number) {
  return (a: T, b: T) => count(b) - count(a) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

export function layoutBipartite(graph: KnowledgeGraph, options: LayoutOptions = {}): BipartiteLayout {
  const width = options.width ?? DEFAULT_WIDTH;
  const rowHeight = options.rowHeight ?? DEFAULT_ROW_HEIGHT;
  const headerHeight = options.headerHeight ?? DEFAULT_HEADER_HEIGHT;
  const leftX = options.leftX ?? DEFAULT_LEFT_X;
  const rightX = options.rightX ?? width - DEFAULT_LEFT_X;

  const documentNodes = graph.nodes.filter((node) => node.node_type === "document");
  const maddeNodes = graph.nodes.filter((node) => node.node_type === "madde");
  const kanunNodes = graph.nodes.filter((node) => node.node_type === "kanun");

  // Breach count per document: how many `ihlal` (rule) edges originate from
  // it -- deliberately edges, not distinct-madde count, so a document
  // missing two fields under the same madde (e.g. imza_sahibi + imza_unvani,
  // both -> m.17) sorts as worse than one missing a single field, matching
  // what "eksik bilgiler (n)" already counts in the analysis panel.
  const breachCountByDocId = new Map<string, number>();
  for (const edge of graph.edges) {
    if (edge.edge_type !== "ihlal") continue;
    breachCountByDocId.set(edge.source, (breachCountByDocId.get(edge.source) ?? 0) + 1);
  }

  const sortedDocuments = [...documentNodes].sort(
    byCountDescThenIdAsc((node) => breachCountByDocId.get(node.id) ?? 0),
  );

  const documentRows: DocumentRow[] = sortedDocuments.map((node, index) => ({
    node,
    x: leftX,
    y: headerHeight + index * rowHeight,
    breachCount: breachCountByDocId.get(node.id) ?? 0,
  }));

  // Group maddeler by kanun so each band is a contiguous block of rows, then
  // order kanun groups by their strongest madde first -- the hub insight
  // (the most-breached madde) then lands at the very top of the right
  // column, where "sorted by degree" makes it visually the fan's apex.
  const maddeByKanun = new Map<string, GraphNode[]>();
  for (const node of maddeNodes) {
    const key = node.kanun ?? "";
    const bucket = maddeByKanun.get(key);
    if (bucket) bucket.push(node);
    else maddeByKanun.set(key, [node]);
  }
  for (const bucket of maddeByKanun.values()) {
    bucket.sort(byCountDescThenIdAsc((node) => node.document_count ?? 0));
  }
  const kanunOrder = [...maddeByKanun.entries()].sort(
    ([, a], [, b]) => (b[0]?.document_count ?? 0) - (a[0]?.document_count ?? 0)
      || (a[0]?.id ?? "").localeCompare(b[0]?.id ?? ""),
  );

  const maddeRows: MaddeRow[] = [];
  const kanunBands: KanunBand[] = [];
  let rowIndex = 0;
  for (const [kanunKey, madde] of kanunOrder) {
    const bandStartY = headerHeight + rowIndex * rowHeight;
    for (const node of madde) {
      maddeRows.push({ node, x: rightX, y: headerHeight + rowIndex * rowHeight });
      rowIndex += 1;
    }
    const kanunNode = kanunNodes.find((node) => node.kanun === kanunKey);
    if (kanunNode) {
      kanunBands.push({ node: kanunNode, y: bandStartY, height: madde.length * rowHeight });
    }
  }

  const positionById = new Map<string, { x: number; y: number }>();
  for (const row of documentRows) positionById.set(row.node.id, { x: row.x, y: row.y });
  for (const row of maddeRows) positionById.set(row.node.id, { x: row.x, y: row.y });
  // A kanun node itself can be an `atif` edge target (a law-only LLM
  // reference, see knowledge_graph.py's three-tier resolution) -- anchor it
  // at its band's vertical midpoint.
  for (const band of kanunBands) {
    positionById.set(band.node.id, { x: rightX, y: band.y + band.height / 2 - rowHeight / 2 });
  }

  const ribbons: Ribbon[] = graph.edges.flatMap((edge) => {
    const from = positionById.get(edge.source);
    const to = positionById.get(edge.target);
    if (!from || !to) return [];
    return [{ edge, path: ribbonPath(from.x, from.y, to.x, to.y) }];
  });

  const rightRowCount = rowIndex;
  const height = headerHeight + Math.max(documentRows.length, rightRowCount, 1) * rowHeight;

  return { documentRows, maddeRows, kanunBands, ribbons, width, height };
}
