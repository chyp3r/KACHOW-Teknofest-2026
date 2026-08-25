import { useEffect, useMemo, useState } from "react";
import { Bot, Clock3, Loader2, Square } from "lucide-react";
import { Button } from "../../components/Button";
import type { ToolCallEvent, WorkflowNodeStatus } from "../../types/chat";
import { deriveWorkflowStages } from "./DecisionFlow";

// A step past this many seconds gets the "taking longer than usual" hint --
// chosen because the median draft attempt (the slowest single step in a
// turn) completes well under it; past this the user is very likely staring
// at a stalled or unusually slow local model call.
const LONG_STEP_SECONDS = 20;

function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}:${seconds.toString().padStart(2, "0")}` : `${seconds} sn`;
}

// Replaces the old static "İstek işleniyor" line with a live view of what
// useChatWorkflow already tracks (nodeStatus/nodeOrder/nodeMeta/nodeResults)
// but nothing previously rendered while a turn was in flight -- a draft turn
// can run 30-90s, and until this component existed the chat pane looked
// identical whether the first second or the eightieth had elapsed.
export function ThinkingBubble({
  planSteps,
  nodeOrder,
  nodeLabels,
  nodeStatus,
  nodeMeta,
  nodeResults,
  toolCalls = [],
  nodeStartedAt,
  turnStartedAt,
  onCancel,
  onRetryFast,
}: {
  planSteps: string[];
  nodeOrder: string[];
  nodeLabels: Record<string, string>;
  nodeStatus: Record<string, WorkflowNodeStatus>;
  nodeMeta: Record<string, Record<string, unknown>>;
  nodeResults: Record<string, Record<string, unknown>>;
  toolCalls?: ToolCallEvent[];
  nodeStartedAt: Record<string, number>;
  turnStartedAt: number | null;
  onCancel?: () => void;
  // Optional "start over at a faster reasoning level" shortcut, offered
  // once a step has been running long enough to suspect it's genuinely
  // slow rather than merely deliberate. Absent when the caller has no last
  // user message to resend (e.g. this turn was itself a resume).
  onRetryFast?: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const stages = useMemo(
    () => deriveWorkflowStages(planSteps, nodeOrder, nodeLabels, nodeStatus, toolCalls),
    [planSteps, nodeOrder, nodeLabels, nodeStatus, toolCalls],
  );

  const runningStage = stages.find((stage) => stage.status === "running");
  const runningStartedAt = runningStage ? nodeStartedAt[runningStage.target] : undefined;
  const runningElapsedMs = runningStartedAt ? now - runningStartedAt : 0;
  const totalElapsedMs = turnStartedAt ? now - turnStartedAt : 0;
  const isLongRunning = runningElapsedMs >= LONG_STEP_SECONDS * 1000;

  const draftMeta = nodeMeta.draft;
  const draftAttempt = typeof draftMeta?.attempt === "number" ? draftMeta.attempt : undefined;
  const draftReasoning = typeof draftMeta?.reasoning_level === "string" ? draftMeta.reasoning_level : undefined;
  const draftInProgress = nodeStatus.draft === "running";
  const draftPreview = typeof nodeResults.draft?.draft === "string" ? nodeResults.draft.draft : "";

  return (
    <article className="chat-message assistant thinking-bubble">
      <span className="message-avatar">
        <Bot size={17} />
      </span>
      <div className="thinking-bubble-body">
        <header className="thinking-bubble-header">
          <span className="thinking-bubble-title">
            <Loader2 className="thinking-bubble-spinner" size={15} aria-hidden="true" />
            Yanıt hazırlanıyor…
          </span>
          {turnStartedAt && (
            <span className="thinking-bubble-elapsed" aria-live="off">
              {formatElapsed(totalElapsedMs)}
            </span>
          )}
        </header>

        {stages.length > 0 && (
          <ul className="thinking-bubble-steps">
            {stages.map((stage) => {
              const stepStartedAt = nodeStartedAt[stage.target];
              const stepElapsed = stage.status === "running" && stepStartedAt ? now - stepStartedAt : 0;
              return (
                <li key={stage.id} className={`thinking-bubble-step is-${stage.status}`}>
                  <span className="thinking-bubble-step-row">
                    <span className="thinking-bubble-step-marker" aria-hidden="true" />
                    <span className="thinking-bubble-step-label">{stage.label}</span>
                    {stage.status === "running" && stepElapsed >= 1000 && (
                      <span className="thinking-bubble-step-time">{formatElapsed(stepElapsed)}</span>
                    )}
                  </span>
                  {stage.subItems && stage.subItems.length > 0 && (
                    <ul className="thinking-bubble-substeps" aria-label={`${stage.label} alt adımları`}>
                      {stage.subItems.map((subItem) => (
                        <li key={subItem.id} className={`thinking-bubble-substep${subItem.status ? ` is-${subItem.status}` : ""}`}>
                          <span className="thinking-bubble-substep-marker" aria-hidden="true" />
                          <span>{subItem.label}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {draftInProgress && draftAttempt !== undefined && (
          <p className="thinking-bubble-subtext">
            {draftAttempt > 1 ? `${draftAttempt}. deneme` : "İlk deneme"}
            {draftReasoning ? ` · ${draftReasoning} mod` : ""}
          </p>
        )}

        {draftInProgress &&
          (draftPreview ? (
            <div className="thinking-bubble-draft-preview" aria-live="polite">
              <p>{draftPreview}</p>
            </div>
          ) : (
            <div className="thinking-bubble-draft-skeleton" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
          ))}

        {isLongRunning && (
          <div className="thinking-bubble-long-wait" role="status">
            <Clock3 size={14} aria-hidden="true" />
            <span>Bu adım normalden uzun sürüyor.</span>
            {onRetryFast && (
              <Button variant="ghost" size="sm" onClick={onRetryFast}>
                Hızlı modda tekrar dene
              </Button>
            )}
          </div>
        )}

        {onCancel && (
          <Button
            className="cancel-stream-button"
            variant="ghost"
            size="sm"
            leadingIcon={<Square size={14} />}
            onClick={onCancel}
          >
            İşlemi durdur
          </Button>
        )}
      </div>
    </article>
  );
}
