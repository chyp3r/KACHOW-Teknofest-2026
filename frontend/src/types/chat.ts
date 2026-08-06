import type { InfoQuestion, ReasoningLevel } from "./documents";

export type WorkflowNodeStatus =
  | "todo"
  | "running"
  | "completed"
  | "failed"
  | "skipped";

export interface WorkflowLog {
  time: string;
  text: string;
}

export interface ChatMessage {
  sender: "user" | "assistant";
  text: string;
  status?: string;
  logs?: WorkflowLog[];
  details?: Record<string, unknown>;
}

export interface InterruptState {
  kind: "missing_information" | "draft_approval";
  interruptId: string;
  payload: {
    questions?: InfoQuestion[];
    draft?: string;
    verification?: Record<string, unknown>;
    judge?: Record<string, unknown>;
    combined_score?: number;
    requires_human_approval?: boolean;
  };
}

interface EventBase {
  seq?: number;
}
export type WorkflowEvent =
  | (EventBase & { event: "session"; thread_id: string })
  | (EventBase & {
      event: "node_start";
      node: string;
      label: string;
      message: string;
      meta?: Record<string, unknown>;
    })
  | (EventBase & {
      event: "node_end";
      node: string;
      label: string;
      message: string;
      result?: Record<string, unknown>;
      meta?: Record<string, unknown>;
    })
  | (EventBase & {
      event: "node_error";
      node: string;
      label: string;
      message: string;
      fatal: boolean;
      detail?: string;
    })
  | (EventBase & {
      event: "node_skipped";
      node: string;
      label: string;
      reason: string;
    })
  | (EventBase & { event: "token"; node: string; text: string })
  | (EventBase & {
      event: "partial_result";
      key: string;
      value: Record<string, unknown>;
    })
  | (EventBase & {
      event: "planning_completed";
      plan_steps: string[];
      intent: string;
      reasoning: string;
    })
  | (EventBase & {
      event: "interrupt";
      kind: InterruptState["kind"];
      interrupt_id: string;
      payload: InterruptState["payload"];
    })
  | (EventBase & {
      event: "final_result";
      reply: string;
      workflow_status: string;
      details?: Record<string, unknown>;
    })
  | (EventBase & { event: "error"; message: string; details?: unknown });

export interface ChatRequest {
  message: string;
  session_id: string | null;
  document_id: string | null;
  reasoning_level: ReasoningLevel;
}

export interface ResumeRequest {
  session_id: string;
  action: "answer" | "approve" | "revise" | "reject";
  answers: Record<string, string>;
  instructions: string;
  reasoning_level?: ReasoningLevel;
}
