import {
  AlertCircle,
  Check,
  ChevronRight,
  Circle,
  Clock3,
  GitBranch,
  X,
  XCircle,
} from "lucide-react";
import { useMemo, useState } from "react";
import type { WorkflowNodeStatus } from "../../types/chat";

interface Stage {
  id: string;
  title: string;
  description: string;
  nodes: string[];
}
const STAGES: Stage[] = [
  {
    id: "planning",
    title: "Yönlendirme",
    description: "İsteğin izlenecek işlem yolu belirlenir.",
    nodes: ["planning"],
  },
  {
    id: "analysis",
    title: "Evrak Analizi",
    description: "Evrak türü ve üst veri alanları çıkarılır.",
    nodes: ["classification"],
  },
  {
    id: "compliance",
    title: "Uygunluk ve Mevzuat Kontrolü",
    description: "Eksik alanlar ve ilgili mevzuat birlikte değerlendirilir.",
    nodes: ["compliance", "rag"],
  },
  {
    id: "draft",
    title: "Taslak Oluşturma",
    description: "Resmî yazı taslağı hazırlanır ve gerektiğinde revize edilir.",
    nodes: ["draft", "revise"],
  },
  {
    id: "quality",
    title: "Doğrulama ve Kalite Kontrolü",
    description: "Kaynak doğrulaması ile anlatım kalitesi değerlendirilir.",
    nodes: ["verify", "judge"],
  },
  {
    id: "approval",
    title: "İnsan Onayı",
    description: "Gerekli olduğunda kullanıcı girdisi veya onay beklenir.",
    nodes: ["human_gate"],
  },
  {
    id: "routing",
    title: "Birim Sevki",
    description: "Evrak için hedef birim önerisi oluşturulur.",
    nodes: ["routing"],
  },
];

function stageStatus(
  stage: Stage,
  statuses: Record<string, WorkflowNodeStatus>,
): WorkflowNodeStatus {
  const values = stage.nodes.map((node) => statuses[node]).filter(Boolean);
  if (values.includes("failed")) return "failed";
  if (values.includes("running")) return "running";
  if (values.some((value) => value === "completed")) return "completed";
  if (values.length && values.every((value) => value === "skipped"))
    return "skipped";
  return "todo";
}

const STATUS_LABELS: Record<WorkflowNodeStatus, string> = {
  todo: "Bekliyor",
  running: "İşleniyor",
  completed: "Tamamlandı",
  failed: "Hata",
  skipped: "Bu akışta yok",
};
const STATUS_ICONS = {
  todo: Circle,
  running: Clock3,
  completed: Check,
  failed: XCircle,
  skipped: ChevronRight,
};

export function DecisionFlow({
  statuses,
  results,
  meta,
  planSteps,
  onClose,
}: {
  statuses: Record<string, WorkflowNodeStatus>;
  results: Record<string, Record<string, unknown>>;
  meta: Record<string, Record<string, unknown>>;
  planSteps: string[];
  onClose?: () => void;
}) {
  const stages = useMemo(
    () =>
      STAGES.map((stage) => ({
        ...stage,
        status: stageStatus(stage, statuses),
      })),
    [statuses],
  );
  const [selectedId, setSelectedId] = useState(STAGES[0].id);
  const selected = stages.find((stage) => stage.id === selectedId) ?? stages[0];
  const technicalData = selected.nodes.reduce<Record<string, unknown>>(
    (data, node) => ({
      ...data,
      [node]: {
        status: statuses[node] ?? "todo",
        result: results[node],
        meta: meta[node],
      },
    }),
    {},
  );
  const branch = statuses.document_qa || statuses.chat;

  return (
    <aside className="workflow-panel" aria-label="Karar akışı">
      <header>
        <div>
          <span className="eyebrow">
            <GitBranch size={14} />
            İşlem süreci
          </span>
          <h2>Karar Akışı</h2>
          <p>İşlemin hangi aşamada olduğunu takip edin.</p>
        </div>
        {onClose && (
          <button
            className="workflow-close icon-button"
            aria-label="Karar akışını kapat"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        )}
      </header>
      <div className="workflow-content">
        <ol className="decision-stepper">
          {stages.map((stage, index) => {
            const Icon = STATUS_ICONS[stage.status];
            return (
              <li key={stage.id} className={`step-${stage.status}`}>
                <button
                  onClick={() => setSelectedId(stage.id)}
                  aria-current={selected.id === stage.id ? "step" : undefined}
                >
                  <span className="step-marker">
                    <Icon size={15} />
                  </span>
                  <span>
                    <small>{index + 1}. aşama</small>
                    <strong>{stage.title}</strong>
                    <em>{STATUS_LABELS[stage.status]}</em>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
        {branch && (
          <div className="subprocess">
            <GitBranch size={16} />
            <div>
              <strong>
                {statuses.document_qa ? "Belge Soru-Cevap" : "Genel Sohbet"}
              </strong>
              <span>Ana karar sürecinden bağımsız kısa işlem</span>
            </div>
          </div>
        )}
        <section className="step-details">
          <div className="section-heading">
            <div>
              <h3>{selected.title}</h3>
              <p>{selected.description}</p>
            </div>
            <span
              className={`status-badge status-${selected.status === "completed" ? "success" : selected.status === "failed" ? "danger" : selected.status === "running" ? "info" : "neutral"}`}
            >
              {STATUS_LABELS[selected.status]}
            </span>
          </div>
          {selected.status === "failed" && (
            <p className="notice danger">
              <AlertCircle size={16} />
              Bu aşamada hata oluştu. Teknik ayrıntıları kontrol edin.
            </p>
          )}
          {selected.id === "approval" && selected.status === "running" && (
            <p className="notice warning">
              <Clock3 size={16} />
              Devam etmek için sohbet alanındaki kullanıcı işlemi bekleniyor.
            </p>
          )}
          <details>
            <summary>Teknik Detaylar</summary>
            <pre>
              {JSON.stringify(
                { plan_steps: planSteps, nodes: technicalData },
                null,
                2,
              )}
            </pre>
          </details>
        </section>
      </div>
    </aside>
  );
}
