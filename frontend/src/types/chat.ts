import type { ReasoningLevel } from "./documents";

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

export interface QuestionOption {
  value: string;
  label: string;
  description?: string;
}

// The canonical shape every "ask the user" surface publishes questions in --
// the pre-draft writing brief, missing-information requests, and clarify's
// intent question all render through one PromptQuestionCard component
// keyed on this type. See backend app.ai.workflows.event_schema.PromptQuestion.
export interface PromptQuestion {
  key: string;
  question: string;
  header?: string;
  help?: string;
  example?: string | null;
  options: QuestionOption[];
  multi_select: boolean;
  allow_free_text: boolean;
  required: boolean;
}

export type InterruptKind =
  | "missing_information"
  | "writing_brief"
  | "artifact_transfer_confirm"
  | "artifact_transfer_disambiguate";

// Read-only receipt left in the conversation after a human-in-the-loop
// question has been answered. Unlike the transport-only resume summary, this
// preserves the original questions and selected values so a reload can
// reconstruct the exchange without exposing internal field keys.
export interface ResolvedPromptInteraction {
  kind: InterruptKind;
  title?: string;
  intro?: string;
  questions: PromptQuestion[];
  resolved?: Record<string, { value: string; label?: string; source?: string }>;
  answers: Record<string, string | string[]>;
  action: "answer" | "approve" | "revise" | "reject" | "select";
  instructions?: string;
  reason?: string;
}

export interface ChatMessage {
  id?: string;
  sender: "user" | "assistant";
  text: string;
  /** Only live final replies opt into the local typewriter effect. */
  animate?: boolean;
  status?: string;
  logs?: WorkflowLog[];
  details?: Record<string, unknown>;
  // "notice" renders as a visually distinct, non-blocking aside (see backend
  // app.ai.workflows.events.emit_notice) -- a conflict warning attached to a
  // revision that was already applied, never a decision the user has to
  // make. Absent (ordinary assistant reply) is the default.
  kind?: "notice";
  // Present on a clarify turn's own message -- rendered through the same
  // PromptQuestionCard every HITL gate uses. Resolved by sending the
  // selected option's label back as the next message (the same thing
  // typing it out by hand would do), per
  // app.ai.workflows.planner._try_resolve_pending_clarification.
  questions?: PromptQuestion[];
  resolvedPrompt?: ResolvedPromptInteraction;
}

/** Bir assist turunun `details.context_usage`'ı -- modelin bağlam
 * penceresinin ne kadarının, ne için kullanıldığı (bkz. backend
 * planning_graph._run_assist). Sohbet alanındaki dairesel gösterge bunu
 * okur; yalnızca assist turları üretir, diğer turlarda alan yoktur. */
export interface ContextUsageSegment {
  key: string;
  label: string;
  tokens: number;
}

export interface ContextUsage {
  total: number;
  used: number;
  free: number;
  segments: ContextUsageSegment[];
}

export interface ChatSession {
  session_id: string;
  title: string | null;
  document_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PersistedChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  workflow_status: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
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

export interface TransferRecipientCandidate {
  user_id: string;
  username: string;
  unit_name?: string | null;
  source?: string;
}

export interface InterruptState {
  // Faz 4 (#201) also includes two transfer gate shapes: candidates
  // unresolved (disambiguate) and the final send confirmation.
  kind: InterruptKind;
  interruptId: string;
  payload: {
    questions?: PromptQuestion[];
    // artifact_transfer_disambiguate only.
    candidates?: TransferRecipientCandidate[];
    // Both transfer interrupt kinds.
    artifact_kind?: "draft" | "document";
    // artifact_transfer_confirm only.
    source_artifact_id?: string;
    source_version?: number | null;
    // Always present on artifact_transfer_confirm, computed server-side
    // (app.domains.transfers.policy.TransferPolicy) -- never derived from
    // model output, so a warning here can't be "forgotten" the way a
    // generated sentence could be.
    cross_unit?: boolean;
    // Slots the writing-brief gate already resolved without asking --
    // rendered as a read-only "bunları zaten biliyorum" strip. Only
    // present on kind "writing_brief".
    resolved?: Record<string, { value: string; label?: string; source?: string }>;
    title?: string;
    intro?: string;
    // "answer" on every gate today -- carried explicitly so the card knows
    // to POST /chat/resume rather than send an ordinary chat message (the
    // clarify "question" event has no resume_action for that reason).
    resume_action?: "answer";
    // The "Sen karar ver" sentinel value -- see backend
    // app.ai.workflows.writing_brief.AUTO_ANSWER. Blank is deliberately
    // never used for this: an empty answer must still count as unanswered
    // so a required-and-skipped slot gets re-asked.
    auto_value?: string;
    round?: number;
    draft?: string;
    verification?: Record<string, unknown>;
    judge?: Record<string, unknown>;
    combined_score?: number;
    requires_human_approval?: boolean;
    conflicts?: ConflictFinding[];
    conflict_notes?: string;
    // Fresh drafts currently carry an empty object; revision entries only
    // become available after a revision has actually been produced.
    changelog?: Partial<RevisionChangelog>;
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
      event: "notice";
      node: string;
      level: "info";
      title: string;
      message: string;
    })
  | (EventBase & {
      event: "question";
      node: string;
      question: string;
      options: QuestionOption[];
      allow_free_text: boolean;
      questions?: PromptQuestion[];
    })
  | (EventBase & {
      event: "final_result";
      reply: string;
      workflow_status: string;
      details?: Record<string, unknown>;
    })
  | (EventBase & {
      event: "error";
      message: string;
      details?: unknown;
      error_code?: string;
    });

export interface ChatRequest {
  message: string;
  session_id: string | null;
  document_id: string | null;
  draft_id: string | null;
  reasoning_level: ReasoningLevel;
}

export interface ResumeRequest {
  session_id: string;
  action: "answer" | "approve" | "revise" | "reject" | "select";
  // A multi_select PromptQuestion answers with a list; every other question
  // shape (including the "__auto__" sentinel) answers with a single string.
  // action="select" carries the chosen candidate as answers.recipient_id --
  // reuses this generic channel rather than a new top-level resume field
  // (see backend ChatResumeRequest.answers's own docstring).
  answers: Record<string, string | string[]>;
  instructions: string;
  reason?: string;
  reasoning_level?: ReasoningLevel;
}

export interface SessionState {
  status: "idle" | "running" | "interrupted";
  interrupt: (InterruptState["payload"] & { kind?: InterruptState["kind"] }) | null;
}
