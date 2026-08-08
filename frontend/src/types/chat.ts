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

// Kind of instruction<->mevzuat/source clash app.ai.revision.conflict can
// find. The instruction is always applied first -- a finding here is a
// warning attached to it, never a reason it was reverted or refused (see
// ConflictReport.applied_anyway on the backend).
export type ConflictKind =
  | "mevzuat_dayanaksiz"
  | "mevzuat_celiskisi"
  | "kaynak_celiskisi"
  | "yapisal_ihlal"
  | "kisisel_veri"
  | "belirsizlik";

export interface ConflictFinding {
  kind: ConflictKind;
  severity: "critical" | "major" | "minor";
  detail: string;
  instruction_fragment?: string;
  evidence?: string;
  source?: "deterministic" | "llm";
}

export interface ChangeEntry {
  directive: string;
  scope: string;
  before: string;
  after: string;
  char_delta: number;
}

export interface RevisionChangelog {
  entries: ChangeEntry[];
  summary: string;
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
    conflicts?: ConflictFinding[];
    conflict_notes?: string;
    changelog?: RevisionChangelog;
    // The human approval gate's own "revizyon iste" loop -- see backend
    // planning_graph.gate_revise_node/route_after_gate. Absent (not just
    // zero) on the very first gate of a turn, before any round has run.
    revision_round?: number;
    max_revision_rounds?: number;
    revision_exhausted?: boolean;
  };
}

interface EventBase {
  seq?: number;
}

export interface ToolCallEvent {
  node: string;
  tool: string;
  args: Record<string, unknown>;
}

export interface GuardrailEvent {
  stage: "input" | "output";
  kind: string;
  decision: "flagged" | "blocked" | "redacted" | "needs_review";
  reasons: string[];
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
      reasoning_level?: ReasoningLevel;
      // Which mechanism produced this decision (fused/fused_semantic/compound/
      // clarification_resolved/model/model_failed/clarify) and how confident it
      // was -- see backend app.ai.workflows.event_schema.PlanningCompletedEvent.
      source?: string;
      confidence?: number;
      alternatives?: [string, number][];
    })
  | (EventBase & { event: "tool_call" } & ToolCallEvent)
  | (EventBase & { event: "guardrail" } & GuardrailEvent)
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
  reason?: string;
  reasoning_level?: ReasoningLevel;
}

export interface SessionState {
  status: "idle" | "running" | "interrupted";
  interrupt: (InterruptState["payload"] & { kind?: InterruptState["kind"] }) | null;
}
