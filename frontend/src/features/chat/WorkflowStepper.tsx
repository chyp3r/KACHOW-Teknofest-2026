import { AlertCircle, Check, Circle, Clock3, Loader2 } from "lucide-react";
import type { WorkflowNodeStatus } from "../../types/chat";
import { StatusBadge, type StatusTone } from "../../components/StatusBadge";

export type WorkflowStageStatus = WorkflowNodeStatus | "interrupted";

export interface WorkflowSubStepItem {
  id: string;
  label: string;
  status?: WorkflowStageStatus;
}

export interface WorkflowStageItem {
  id: string;
  label: string;
  description: string;
  status: WorkflowStageStatus;
  target: string;
  subItems?: WorkflowSubStepItem[];
}

const STATUS_LABELS: Record<WorkflowStageStatus, string> = {
  todo: "Bekliyor",
  running: "Çalışıyor",
  completed: "Tamamlandı",
  failed: "Hata",
  skipped: "Atlandı",
  interrupted: "Yanıtınız bekleniyor",
};

function tone(status: WorkflowStageStatus): StatusTone {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "running") return "info";
  if (status === "interrupted") return "warning";
  return "neutral";
}

function Marker({ status }: { status: WorkflowStageStatus }) {
  if (status === "completed") return <Check />;
  if (status === "running") return <Loader2 />;
  if (status === "failed") return <AlertCircle />;
  if (status === "interrupted") return <Clock3 />;
  return <Circle />;
}

export function WorkflowStepper({
  stages,
  onSelect,
}: {
  stages: WorkflowStageItem[];
  onSelect: (target: string) => void;
}) {
  return (
    <ol className="workflow-stepper" aria-label="İş akışı adımları">
      {stages.map((stage) => (
        <li key={stage.id} className={`workflow-step workflow-step-${stage.status}`}>
          <button
            type="button"
            className="workflow-step-button"
            aria-current={stage.status === "running" || stage.status === "interrupted" ? "step" : undefined}
            onClick={() => onSelect(stage.target)}
          >
            <span className="workflow-step-rail" aria-hidden="true">
              <span className="workflow-step-marker"><Marker status={stage.status} /></span>
            </span>
            <span className="workflow-step-content">
              <span className="workflow-step-heading">
                <strong>{stage.label}</strong>
                <StatusBadge tone={tone(stage.status)}>{STATUS_LABELS[stage.status]}</StatusBadge>
              </span>
              <span className="workflow-step-description">{stage.description}</span>
              {stage.subItems && stage.subItems.length > 0 && (
                <ul className="workflow-step-substeps">
                  {stage.subItems.map((subItem) => (
                    <li key={subItem.id}>
                      <span>{subItem.label}</span>
                      {subItem.status && (
                        <StatusBadge tone={tone(subItem.status)}>{STATUS_LABELS[subItem.status]}</StatusBadge>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}
