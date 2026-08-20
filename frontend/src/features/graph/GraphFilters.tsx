import { Button } from "../../components/Button";
import { Card } from "../../components/Surface";
import type { GraphEdge, GraphNode } from "../../types/documents";

const NODE_TYPE_OPTIONS: Array<{ type: GraphNode["node_type"]; label: string }> = [
  { type: "document", label: "Evrak" },
  { type: "entity", label: "Kurum/Kişi" },
  { type: "madde", label: "Madde" },
  { type: "kanun", label: "Kanun" },
  { type: "konu", label: "Konu" },
];

const EDGE_TYPE_OPTIONS: Array<{ type: GraphEdge["edge_type"]; label: string; kind: "rule" | "llm" }> = [
  { type: "ihlal", label: "İhlal (kural)", kind: "rule" },
  { type: "muhatap", label: "Muhatap (kural)", kind: "rule" },
  { type: "gonderen", label: "Gönderen (kural)", kind: "rule" },
  { type: "konu", label: "Konu (kural)", kind: "rule" },
  { type: "atif", label: "Mevzuat atfı (model önerisi)", kind: "llm" },
  { type: "bahseder", label: "Bahseder (model önerisi)", kind: "llm" },
];

/** Node-type and edge-type toggles for the unified graph, plus the two
 * presets: "compliance" (reproduces exactly what PR #212 shipped -- see
 * `filters.ts`'s `filterToComplianceOnly`) and "unified" (everything).
 * A controlled component throughout -- all state (which types are
 * currently allowed, which mode is active) lives in the parent. */
export function GraphFilters({
  mode,
  nodeTypes,
  edgeTypes,
  onToggleNodeType,
  onToggleEdgeType,
  onSelectPreset,
}: {
  mode: "unified" | "compliance";
  nodeTypes: Set<GraphNode["node_type"]>;
  edgeTypes: Set<GraphEdge["edge_type"]>;
  onToggleNodeType: (type: GraphNode["node_type"]) => void;
  onToggleEdgeType: (type: GraphEdge["edge_type"]) => void;
  onSelectPreset: (preset: "unified" | "compliance") => void;
}) {
  return (
    <Card className="graph-filters" role="region" aria-label="Grafik filtreleri">
      <div className="graph-filters-presets">
        <Button
          variant={mode === "compliance" ? "primary" : "outline"}
          size="sm"
          onClick={() => onSelectPreset("compliance")}
        >
          Sadece uyum
        </Button>
        <Button
          variant={mode === "unified" ? "primary" : "outline"}
          size="sm"
          onClick={() => onSelectPreset("unified")}
        >
          Tüm graf
        </Button>
      </div>

      {mode === "unified" && (
        <>
          <fieldset className="graph-filters-group">
            <legend>Düğüm türleri</legend>
            {NODE_TYPE_OPTIONS.map((option) => (
              <label key={option.type} className="graph-filters-checkbox">
                <input
                  type="checkbox"
                  checked={nodeTypes.has(option.type)}
                  onChange={() => onToggleNodeType(option.type)}
                />
                {option.label}
              </label>
            ))}
          </fieldset>

          <fieldset className="graph-filters-group">
            <legend>Bağlantı türleri</legend>
            {EDGE_TYPE_OPTIONS.map((option) => (
              <label key={option.type} className={`graph-filters-checkbox graph-filters-${option.kind}`}>
                <input
                  type="checkbox"
                  checked={edgeTypes.has(option.type)}
                  onChange={() => onToggleEdgeType(option.type)}
                />
                {option.label}
              </label>
            ))}
          </fieldset>
        </>
      )}
    </Card>
  );
}
