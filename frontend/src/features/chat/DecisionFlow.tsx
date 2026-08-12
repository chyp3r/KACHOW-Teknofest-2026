import { AlertCircle, ChevronDown, Clock3, GitBranch, X } from "lucide-react";
import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import type {
  GuardrailEvent,
  ToolCallEvent,
  WorkflowNodeStatus,
} from "../../types/chat";
import { InteractiveGraphViewport } from "./InteractiveGraphViewport";
import { Button, IconButton } from "../../components/Button";
import { StatusBadge, type StatusTone } from "../../components/StatusBadge";
import { Alert } from "../../components/Surface";
import { WorkflowStepper, type WorkflowStageItem } from "./WorkflowStepper";

interface GraphNode {
  id: string;
  kind: "llm" | "rule" | "io";
  x: number;
  y: number;
}

interface GraphEdge {
  from: string;
  to: string;
  parallel?: boolean;
  back?: boolean;
}

// The complete id -> label/description registry for every node the backend
// can put on the SSE stream (see backend app.ai.workflows.event_schema and
// each graph's own emit_node_start/end call sites). Only a subset of these
// are drawn in the technical graph below (see NODES) -- the rest (sub-steps
// of draft/revise/human_gate, see SUB_STEPS) still need a label/description
// for the dynamic stepper and its detail panel. These are fallbacks only:
// a node_start/end/error/skipped event's own `label` (see useChatWorkflow's
// nodeLabels) always wins when it has arrived.
const NODE_INFO: Record<string, { label: string; short: string; description: string }> = {
  planning: { label: "Yönlendirici", short: "ROTA", description: "İsteği deterministik kurallarla uygun işlem yoluna yönlendirir." },
  classification: { label: "Evrak Analizi", short: "ANALİZ", description: "Evrak türünü ve zorunlu üst veri alanlarını çıkarır." },
  rag: { label: "Mevzuat", short: "RAG", description: "İlgili mevzuatı hibrit aramayla getirir ve kanıt bağlamını kurar." },
  examples: { label: "Üslup Örnekleri", short: "ÖRNEK", description: "Benzer resmî yazılardan üslup örnekleri getirir." },
  brief: { label: "Yazım Briefi", short: "BRIEF", description: "Taslak öncesi yazım stilini (taraf, muhatap, kapanış vb.) çözümler." },
  brief_gate: { label: "Yazım Briefi", short: "BRIEF", description: "Yazım briefindeki belirsiz yuvalar için kullanıcıya sorar." },
  draft: { label: "Taslak", short: "YAZAR", description: "Belge ve mevzuat bağlamından resmî yazı taslağı oluşturur." },
  verify: { label: "Doğrulama", short: "KANIT", description: "Taslağın iddialarını kaynak evrak ve mevzuata karşı denetler." },
  judge: { label: "Kalite Yargıcı", short: "YARGIÇ", description: "Talebe uygunluk, resmî üslup ve muhatap tutarlılığını değerlendirir." },
  revise: { label: "Revizyon", short: "REVİZE", description: "Doğrulama ve kalite bulgularını düzeltme listesine dönüştürür." },
  revise_parse: { label: "Talimat Ayrıştırma", short: "AYRIŞTIR", description: "Kullanıcı talimatını yapılandırılmış revizyon direktiflerine ayrıştırır." },
  revise_retrieve: { label: "Mevzuat Kontrolü", short: "MEVZUAT", description: "Revizyon için ilgili mevzuatı yeniden getirir." },
  revise_repair: { label: "Revizyon Onarımı", short: "ONARIM", description: "Doğrulama bulgularını yeni bir düzeltme turuna dönüştürür." },
  revise_audit: { label: "Çelişki Denetimi", short: "DENETİM", description: "Uygulanan talimatla mevzuat/kaynak arasında çelişki olup olmadığını denetler." },
  human_gate: { label: "İnsan Onayı", short: "ONAY", description: "Eksik bilgi veya onay gerektiğinde akışı güvenli biçimde durdurur." },
  gate_revise: { label: "Geri Bildirimli Revizyon", short: "GERİ BLD.", description: 'Onay kapısındaki "Revizyon iste" talebinizi aynı çalışmada uygular ve kapıya geri döner.' },
  routing: { label: "Birim Sevki", short: "SEVK", description: "Tamamlanan taslak için hedef birimi gerekçesiyle önerir." },
  assist: { label: "Asistan", short: "ASİST", description: "Belge ve mevzuat araçlarını kullanarak kaynaklı sohbet yanıtı hazırlar." },
  clarify: { label: "Açıklayıcı Soru", short: "SORU", description: "İsteği netleştirmek için kullanıcıya seçenekli bir soru sorar." },
  refuse: { label: "Kapsam Denetimi", short: "KAPSAM", description: "İsteğin sistemin görev alanı dışında kaldığını belirler ve yetenek listesini döndürür." },
};

// Only the nodes hand-positioned on the technical graph's SVG canvas.
// "compliance" was removed here -- it is never a real node (only an
// emit_partial key, see document_analysis_graph.py), so it could never
// actually reach a "running"/"completed" status on this graph.
const NODES: GraphNode[] = [
  { id: "planning", kind: "rule", x: 280, y: 50 },
  { id: "classification", kind: "llm", x: 160, y: 145 },
  { id: "rag", kind: "io", x: 230, y: 240 },
  { id: "draft", kind: "llm", x: 220, y: 335 },
  { id: "revise", kind: "rule", x: 75, y: 335 },
  { id: "verify", kind: "rule", x: 145, y: 430 },
  { id: "judge", kind: "llm", x: 290, y: 430 },
  { id: "human_gate", kind: "io", x: 220, y: 525 },
  { id: "gate_revise", kind: "rule", x: 150, y: 630 },
  { id: "routing", kind: "llm", x: 400, y: 525 },
  { id: "assist", kind: "llm", x: 440, y: 210 },
];

const EDGES: GraphEdge[] = [
  { from: "planning", to: "classification" },
  { from: "planning", to: "assist" },
  { from: "classification", to: "rag", parallel: true },
  { from: "classification", to: "draft" },
  { from: "rag", to: "draft" },
  { from: "draft", to: "verify" },
  { from: "draft", to: "judge" },
  { from: "verify", to: "human_gate" },
  { from: "judge", to: "human_gate" },
  { from: "human_gate", to: "routing" },
  { from: "verify", to: "revise", back: true },
  { from: "revise", to: "draft", back: true },
  { from: "human_gate", to: "gate_revise", back: true },
  { from: "gate_revise", to: "human_gate", back: true },
];

const STATUS_LABELS: Record<WorkflowNodeStatus, string> = {
  todo: "Bekliyor",
  running: "Çalışıyor",
  completed: "Tamamlandı",
  failed: "Hata",
  skipped: "Atlandı",
};

const NODE_STROKES: Record<GraphNode["kind"], string> = {
  rule: "var(--workflow-rule)",
  io: "var(--workflow-io)",
  llm: "var(--workflow-llm)",
};

const STATUS_STROKES: Partial<Record<WorkflowNodeStatus, string>> = {
  running: "var(--status-running)",
  completed: "var(--status-completed)",
  failed: "var(--status-failed)",
  skipped: "var(--status-skipped)",
};

function statusTone(status: WorkflowNodeStatus): StatusTone {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "running") return "info";
  return "neutral";
}

// One-line subtitles for the top-level stages the dynamic stepper renders.
// Falls back to NODE_INFO's own description, then to an empty string --
// unlike NODE_INFO this is deliberately only filled in for nodes that
// actually head a stage (see SUB_STEPS' keys).
const STAGE_DESCRIPTIONS: Record<string, string> = {
  classification: "Belge türü, alanlar ve mevzuat bağlamı",
  draft: "Resmî yazı ve gerekli revizyonlar",
  human_gate: "Eksik bilgi veya kullanıcı kararı",
  routing: "Hedef birim önerisi",
  assist: "Belge ve mevzuat araçları gerektiğinde kullanılır",
};

// Which nodes collapse into which stage's sub-items instead of getting
// their own top-level row. A node not listed here (or not claimed because
// its owner hasn't appeared yet -- see the ownership loop below) always
// gets its own stage, so a new backend node is never silently dropped.
const SUB_STEPS: Record<string, string[]> = {
  classification: ["rag"],
  brief: ["brief_gate"],
  draft: ["examples", "verify", "judge"],
  revise: ["revise_parse", "revise_retrieve", "revise_repair", "revise_audit", "verify", "judge"],
  human_gate: ["gate_revise"],
};

function stageStatus(
  nodes: string[],
  statuses: Record<string, WorkflowNodeStatus>,
): WorkflowNodeStatus {
  const values = nodes.map((node) => statuses[node] ?? "todo");
  if (values.includes("failed")) return "failed";
  if (values.includes("running")) return "running";
  if (values.some((value) => value === "completed")) return "completed";
  if (values.every((value) => value === "skipped")) return "skipped";
  return "todo";
}

function dedupe(ids: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const id of ids) {
    if (seen.has(id)) continue;
    seen.add(id);
    result.push(id);
  }
  return result;
}

export function DecisionFlow({
  statuses,
  results,
  meta,
  planSteps,
  nodeLabels = {},
  nodeOrder = [],
  planIntent = "",
  toolCalls = [],
  guardrailEvents = [],
  onClose,
}: {
  statuses: Record<string, WorkflowNodeStatus>;
  results: Record<string, Record<string, unknown>>;
  meta: Record<string, Record<string, unknown>>;
  planSteps: string[];
  nodeLabels?: Record<string, string>;
  nodeOrder?: string[];
  planIntent?: string;
  toolCalls?: ToolCallEvent[];
  guardrailEvents?: GuardrailEvent[];
  onClose?: () => void;
}) {
  const [selectedId, setSelectedId] = useState("planning");
  const [technicalOpen, setTechnicalOpen] = useState(false);
  const selectedInfo = NODE_INFO[selectedId] ?? NODE_INFO.planning;
  const selectedLabel = nodeLabels[selectedId] ?? selectedInfo.label;
  const selectedStatus = statuses[selectedId] ?? "todo";
  const selectedData = useMemo(
    () => ({
      status: selectedStatus,
      result: results[selectedId],
      meta: meta[selectedId],
    }),
    [meta, results, selectedId, selectedStatus],
  );
  const planLabels = planSteps.map(
    (step) => nodeLabels[step] ?? NODE_INFO[step]?.label ?? step,
  );

  // Derives the stepper's stage list from what this turn actually planned
  // (planSteps) plus every node the backend has announced so far
  // (nodeOrder), instead of a fixed 5-stage list -- an analyze-only turn
  // shows just its analysis step, an assist turn shows the assistant and
  // its tool calls, and a draft turn shows the full chain with verify/judge
  // etc. folded under their owning step. "planning" needs no special
  // handling to stay visible: it is the very first node_start the backend
  // emits, so nodeOrder already carries it before anything else can arrive.
  const stages: WorkflowStageItem[] = useMemo(() => {
    const ordered = dedupe([...planSteps, ...nodeOrder]);
    const owner = new Map<string, string>();
    for (const stageId of ordered) {
      for (const sub of SUB_STEPS[stageId] ?? []) {
        if (sub === stageId || owner.has(sub) || planSteps.includes(sub)) continue;
        owner.set(sub, stageId);
      }
    }
    const stageIds = ordered.filter((id) => !owner.has(id));

    const toolsByOwner = new Map<string, Map<string, number>>();
    for (const call of toolCalls) {
      const ownerId = owner.get(call.node) ?? call.node;
      const perTool = toolsByOwner.get(ownerId) ?? new Map<string, number>();
      perTool.set(call.tool, (perTool.get(call.tool) ?? 0) + 1);
      toolsByOwner.set(ownerId, perTool);
    }

    return stageIds.map((stageId): WorkflowStageItem => {
      const ownedSubs = ordered.filter((id) => owner.get(id) === stageId);
      const nodes = [stageId, ...ownedSubs];
      const status = stageStatus(nodes, statuses);
      const needsAction = stageId === "human_gate" && status === "running";
      const subItems = [
        ...ownedSubs
          .filter((sub) => (statuses[sub] ?? "todo") !== "todo")
          .map((sub) => ({
            id: sub,
            label: nodeLabels[sub] ?? NODE_INFO[sub]?.label ?? sub,
            status: statuses[sub] ?? "todo",
          })),
        ...Array.from(toolsByOwner.get(stageId)?.entries() ?? []).map(([tool, count]) => ({
          id: `tool:${tool}`,
          label: count > 1 ? `${tool} ×${count}` : tool,
        })),
      ];
      return {
        id: stageId,
        label: nodeLabels[stageId] ?? NODE_INFO[stageId]?.label ?? stageId,
        description: STAGE_DESCRIPTIONS[stageId] ?? NODE_INFO[stageId]?.description ?? "",
        status: needsAction ? "interrupted" : status,
        target:
          nodes.find((node) => statuses[node] === "failed" || statuses[node] === "running") ??
          stageId,
        subItems: subItems.length > 0 ? subItems : undefined,
      };
    });
  }, [planSteps, nodeOrder, nodeLabels, statuses, toolCalls]);

  const selectWithKeyboard = (
    event: KeyboardEvent<SVGGElement>,
    nodeId: string,
  ) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    setSelectedId(nodeId);
  };
  useEffect(() => {
    if (!onClose) return;
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <aside className={`workflow-panel workflow-graph-panel ${technicalOpen ? "is-technical-open" : ""}`} aria-label="İş akışı">
      <header>
        <div>
          <span className="eyebrow">
            <GitBranch size={14} />
            İşlem durumu
          </span>
          <h2>İş Akışı</h2>
          <p>Şu an ne olduğunu ve sıradaki adımı takip edin.</p>
        </div>
        {onClose && (
          <IconButton
            className="workflow-close"
            icon={<X />}
            aria-label="İş akışını kapat"
            onClick={onClose}
          />
        )}
      </header>

      <div className="workflow-content">
        <div className="workflow-plan-summary">
          <span>Seçilen plan</span>
          <strong>
            {planLabels.length > 0
              ? planLabels.join(" → ")
              : "Mesaj gönderildiğinde plan burada görünecek."}
          </strong>
        </div>

        <WorkflowStepper stages={stages} onSelect={setSelectedId} />

        <section className={`technical-workflow ${technicalOpen ? "is-open" : ""}`}>
          <Button
            className="technical-workflow-toggle"
            variant="ghost"
            fullWidth
            aria-expanded={technicalOpen}
            leadingIcon={<GitBranch size={15} />}
            trailingIcon={<ChevronDown className="technical-workflow-chevron" />}
            onClick={() => setTechnicalOpen((open) => !open)}
          >
            {technicalOpen ? "Teknik grafiği gizle" : "Teknik grafiği görüntüle"}
          </Button>
          {technicalOpen && (
            <div className="technical-workflow-content">
              <InteractiveGraphViewport ariaLabel="Karar akışı düğüm grafiği">
            {EDGES.map((edge) => {
              const from = NODES.find((node) => node.id === edge.from);
              const to = NODES.find((node) => node.id === edge.to);
              if (!from || !to) return null;
              const status = statuses[edge.to] ?? "todo";
              if (edge.back && status === "skipped") return null;
              return (
                <line
                  key={`${edge.from}-${edge.to}`}
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                  className={`link-line ${status}`}
                  strokeDasharray={edge.parallel || edge.back ? "5 4" : undefined}
                  opacity={edge.back ? 0.65 : undefined}
                />
              );
            })}

            {NODES.map((node) => {
              const info = NODE_INFO[node.id];
              const label = nodeLabels[node.id] ?? info?.label ?? node.id;
              const status = statuses[node.id] ?? "todo";
              const stroke = STATUS_STROKES[status] ?? NODE_STROKES[node.kind];
              const nodeMeta = meta[node.id];
              const attempt =
                typeof nodeMeta?.attempt === "number" && nodeMeta.attempt > 1
                  ? ` #${nodeMeta.attempt}`
                  : "";
              return (
                <g
                  key={node.id}
                  className={`node ${status} ${selectedId === node.id ? "is-selected" : ""}`}
                  role="button"
                  tabIndex={0}
                  aria-label={`${label}: ${STATUS_LABELS[status]}`}
                  onClick={() => setSelectedId(node.id)}
                  onKeyDown={(event) => selectWithKeyboard(event, node.id)}
                >
                  <circle
                    cx={node.x}
                    cy={node.y}
                    r={36}
                    style={{
                      stroke,
                      strokeWidth: selectedId === node.id ? 4 : 2.5,
                    }}
                  />
                  <text x={node.x} y={node.y + 3} className="node-short">
                    {info?.short ?? label}
                  </text>
                  <text x={node.x} y={node.y + 48} className="node-label">
                    {label}{attempt}
                  </text>
                </g>
              );
            })}
              </InteractiveGraphViewport>

        <div className="workflow-legend" aria-label="Düğüm türleri">
          <span className="legend-rule">Deterministik</span>
          <span className="legend-llm">Model</span>
          <span className="legend-io">Araç / insan</span>
        </div>

        {(toolCalls.length > 0 || guardrailEvents.length > 0) && (
          <div className="workflow-signal-grid">
            {toolCalls.length > 0 && (
              <div className="subprocess">
                <GitBranch size={16} />
                <div>
                  <strong>{toolCalls.length} araç çağrısı</strong>
                  <span>{toolCalls.map((call) => call.tool).join(" · ")}</span>
                </div>
              </div>
            )}
            {guardrailEvents.length > 0 && (
              <div className="subprocess guardrail-process">
                <AlertCircle size={16} />
                <div>
                  <strong>Güvenlik kararı</strong>
                  <span>
                    {guardrailEvents.map((event) => event.decision).join(" · ")}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        <section className="step-details graph-step-details">
          <div className="section-heading">
            <div>
              <h3>{selectedLabel}</h3>
              <p>{selectedInfo.description}</p>
            </div>
            <StatusBadge tone={statusTone(selectedStatus)}>
              {STATUS_LABELS[selectedStatus]}
            </StatusBadge>
          </div>
          {selectedStatus === "failed" && (
            <Alert variant="error" icon={<AlertCircle />}>Bu adımda hata oluştu. Teknik ayrıntıyı aşağıdan inceleyin.</Alert>
          )}
          {selectedId === "human_gate" && selectedStatus === "running" && (
            <Alert variant="warning" icon={<Clock3 />}>Sohbet alanında kullanıcı yanıtı veya onayı bekleniyor.</Alert>
          )}
          <details>
            <summary>Teknik detaylar</summary>
            <pre>
              {JSON.stringify(
                {
                  plan_steps: planSteps,
                  intent: planIntent,
                  node: selectedData,
                  tools: toolCalls.filter((call) => call.node === selectedId),
                  guardrails: guardrailEvents,
                },
                null,
                2,
              )}
            </pre>
          </details>
              </section>
            </div>
          )}
        </section>
      </div>
    </aside>
  );
}
