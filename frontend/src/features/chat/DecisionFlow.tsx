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
  label: string;
  short: string;
  kind: "llm" | "rule" | "io";
  x: number;
  y: number;
  description: string;
}

interface GraphEdge {
  from: string;
  to: string;
  parallel?: boolean;
  back?: boolean;
}

const NODES: GraphNode[] = [
  {
    id: "planning",
    label: "Yönlendirici",
    short: "ROTA",
    kind: "rule",
    x: 280,
    y: 50,
    description: "İsteği deterministik kurallarla uygun işlem yoluna yönlendirir.",
  },
  {
    id: "classification",
    label: "Evrak Analizi",
    short: "ANALİZ",
    kind: "llm",
    x: 160,
    y: 145,
    description: "Evrak türünü ve zorunlu üst veri alanlarını çıkarır.",
  },
  {
    id: "compliance",
    label: "Uygunluk",
    short: "KURAL",
    kind: "rule",
    x: 90,
    y: 240,
    description: "Belge türüne göre zorunlu alanları deterministik olarak denetler.",
  },
  {
    id: "rag",
    label: "Mevzuat",
    short: "RAG",
    kind: "io",
    x: 230,
    y: 240,
    description: "İlgili mevzuatı hibrit aramayla getirir ve kanıt bağlamını kurar.",
  },
  {
    id: "draft",
    label: "Taslak",
    short: "YAZAR",
    kind: "llm",
    x: 220,
    y: 335,
    description: "Belge ve mevzuat bağlamından resmî yazı taslağı oluşturur.",
  },
  {
    id: "revise",
    label: "Revizyon",
    short: "REVİZE",
    kind: "rule",
    x: 75,
    y: 335,
    description: "Doğrulama ve kalite bulgularını düzeltme listesine dönüştürür.",
  },
  {
    id: "verify",
    label: "Doğrulama",
    short: "KANIT",
    kind: "rule",
    x: 145,
    y: 430,
    description: "Taslağın iddialarını kaynak evrak ve mevzuata karşı denetler.",
  },
  {
    id: "judge",
    label: "Kalite Yargıcı",
    short: "YARGIÇ",
    kind: "llm",
    x: 290,
    y: 430,
    description: "Talebe uygunluk, resmî üslup ve muhatap tutarlılığını değerlendirir.",
  },
  {
    id: "human_gate",
    label: "İnsan Onayı",
    short: "ONAY",
    kind: "io",
    x: 220,
    y: 525,
    description: "Eksik bilgi veya onay gerektiğinde akışı güvenli biçimde durdurur.",
  },
  {
    id: "gate_revise",
    label: "Geri Bildirimli Revizyon",
    short: "GERİ BLD.",
    kind: "rule",
    x: 150,
    y: 630,
    description:
      'Onay kapısındaki "Revizyon iste" talebinizi aynı çalışmada uygular ve kapıya geri döner.',
  },
  {
    id: "routing",
    label: "Birim Sevki",
    short: "SEVK",
    kind: "llm",
    x: 400,
    y: 525,
    description: "Tamamlanan taslak için hedef birimi gerekçesiyle önerir.",
  },
  {
    id: "assist",
    label: "Asistan",
    short: "ASİST",
    kind: "llm",
    x: 440,
    y: 210,
    description: "Belge ve mevzuat araçlarını kullanarak kaynaklı sohbet yanıtı hazırlar.",
  },
];

const EDGES: GraphEdge[] = [
  { from: "planning", to: "classification" },
  { from: "planning", to: "assist" },
  { from: "classification", to: "compliance", parallel: true },
  { from: "classification", to: "rag", parallel: true },
  { from: "compliance", to: "draft" },
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

const WORKFLOW_STAGES: Array<{
  id: string;
  label: string;
  description: string;
  nodes: string[];
}> = [
  { id: "analysis", label: "Evrak analizi", description: "Belge türü, alanlar ve mevzuat bağlamı", nodes: ["classification", "compliance", "rag"] },
  { id: "drafting", label: "Taslak oluşturma", description: "Resmî yazı ve gerekli revizyonlar", nodes: ["draft", "revise", "gate_revise"] },
  { id: "verification", label: "Doğrulama", description: "Kaynak, uygunluk ve kalite kontrolleri", nodes: ["verify", "judge"] },
  { id: "approval", label: "İnsan onayı", description: "Eksik bilgi veya kullanıcı kararı", nodes: ["human_gate"] },
  { id: "routing", label: "Yönlendirme", description: "Hedef birim önerisi", nodes: ["routing"] },
];

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

export function DecisionFlow({
  statuses,
  results,
  meta,
  planSteps,
  toolCalls = [],
  guardrailEvents = [],
  onClose,
}: {
  statuses: Record<string, WorkflowNodeStatus>;
  results: Record<string, Record<string, unknown>>;
  meta: Record<string, Record<string, unknown>>;
  planSteps: string[];
  toolCalls?: ToolCallEvent[];
  guardrailEvents?: GuardrailEvent[];
  onClose?: () => void;
}) {
  const [selectedId, setSelectedId] = useState("planning");
  const [technicalOpen, setTechnicalOpen] = useState(false);
  const selected = NODES.find((node) => node.id === selectedId) ?? NODES[0];
  const selectedStatus = statuses[selected.id] ?? "todo";
  const selectedData = useMemo(
    () => ({
      status: selectedStatus,
      result: results[selected.id],
      meta: meta[selected.id],
    }),
    [meta, results, selected.id, selectedStatus],
  );
  const planLabels = planSteps.map(
    (step) => NODES.find((node) => node.id === step)?.label ?? step,
  );
  const stages: WorkflowStageItem[] = WORKFLOW_STAGES.map((stage) => {
    const status = stageStatus(stage.nodes, statuses);
    const needsAction = stage.id === "approval" && status === "running";
    return {
      ...stage,
      status: needsAction ? "interrupted" : status,
      target: stage.nodes.find((node) => statuses[node] === "failed" || statuses[node] === "running") ?? stage.nodes[0],
    };
  });

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

        {statuses.assist && statuses.assist !== "todo" && (
          <div className={`workflow-assist-state stage-${statuses.assist}`}>
            <span className="workflow-stage-marker"><GitBranch size={15} /></span>
            <div><strong>Yanıt hazırlanıyor</strong><small>Belge ve mevzuat araçları gerektiğinde kullanılır.</small></div>
            <span>{STATUS_LABELS[statuses.assist]}</span>
          </div>
        )}

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
                  className={`node ${status} ${selected.id === node.id ? "is-selected" : ""}`}
                  role="button"
                  tabIndex={0}
                  aria-label={`${node.label}: ${STATUS_LABELS[status]}`}
                  onClick={() => setSelectedId(node.id)}
                  onKeyDown={(event) => selectWithKeyboard(event, node.id)}
                >
                  <circle
                    cx={node.x}
                    cy={node.y}
                    r={36}
                    style={{
                      stroke,
                      strokeWidth: selected.id === node.id ? 4 : 2.5,
                    }}
                  />
                  <text x={node.x} y={node.y + 3} className="node-short">
                    {node.short}
                  </text>
                  <text x={node.x} y={node.y + 48} className="node-label">
                    {node.label}{attempt}
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
              <h3>{selected.label}</h3>
              <p>{selected.description}</p>
            </div>
            <StatusBadge tone={statusTone(selectedStatus)}>
              {STATUS_LABELS[selectedStatus]}
            </StatusBadge>
          </div>
          {selectedStatus === "failed" && (
            <Alert variant="error" icon={<AlertCircle />}>Bu adımda hata oluştu. Teknik ayrıntıyı aşağıdan inceleyin.</Alert>
          )}
          {selected.id === "human_gate" && selectedStatus === "running" && (
            <Alert variant="warning" icon={<Clock3 />}>Sohbet alanında kullanıcı yanıtı veya onayı bekleniyor.</Alert>
          )}
          <details>
            <summary>Teknik detaylar</summary>
            <pre>
              {JSON.stringify(
                {
                  plan_steps: planSteps,
                  node: selectedData,
                  tools: toolCalls.filter((call) => call.node === selected.id),
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
