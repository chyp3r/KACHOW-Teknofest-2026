import { apiErrorFromResponse, apiFetch, apiRequest } from "./apiClient";
import type {
  ChatRequest,
  ChatSession,
  PersistedChatMessage,
  ResumeRequest,
  SessionState,
  WorkflowEvent,
} from "../types/chat";
import type { PaginatedResponse } from "../types/api";
import { collectPages } from "./pagination";

function isWorkflowEvent(value: unknown): value is WorkflowEvent {
  if (typeof value !== "object" || value === null) return false;
  const event = value as Record<string, unknown>;
  if (event.seq !== undefined && typeof event.seq !== "number") return false;
  const strings = (...keys: string[]) => keys.every((key) => typeof event[key] === "string");
  const record = (key: string) =>
    typeof event[key] === "object" && event[key] !== null && !Array.isArray(event[key]);
  const stringArray = (key: string) =>
    Array.isArray(event[key]) && event[key].every((item) => typeof item === "string");

  switch (event.event) {
    case "session":
      return strings("thread_id");
    case "planning_completed":
      return strings("intent", "reasoning") && stringArray("plan_steps");
    case "node_start":
      return strings("node", "label", "message");
    case "node_end":
      return strings("node", "label", "message");
    case "node_error":
      return strings("node", "label", "message") && typeof event.fatal === "boolean";
    case "node_skipped":
      return strings("node", "label", "reason");
    case "token":
      return strings("node", "text");
    case "partial_result":
      return strings("key") && record("value");
    case "tool_call":
      return strings("node", "tool") && record("args");
    case "guardrail":
      return strings("stage", "kind", "decision") && stringArray("reasons");
    case "interrupt":
      return strings("kind", "interrupt_id") && record("payload");
    case "notice":
      return strings("node", "level", "title", "message");
    case "question":
      return strings("node", "question") && Array.isArray(event.options);
    case "final_result":
      return strings("reply", "workflow_status");
    case "error":
      return strings("message");
    default:
      return false;
  }
}

export async function consumeSseStream(
  response: Response,
  onEvent: (event: WorkflowEvent) => void,
): Promise<void> {
  if (!response.ok) throw await apiErrorFromResponse(response);
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Sunucu akış yanıtı göndermedi.");

  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let lastSequence = Number.NEGATIVE_INFINITY;

  const consumeBlock = (block: string) => {
    const raw = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n")
      .trim();
    if (!raw || raw === "[DONE]") return;
    let candidate: unknown;
    try {
      candidate = JSON.parse(raw);
    } catch {
      return;
    }
    if (!isWorkflowEvent(candidate)) return;
    const event = candidate;
    if (event.seq !== undefined) {
      if (event.seq <= lastSequence) return;
      lastSequence = event.seq;
    }
    onEvent(event);
  };

  let streamEnded = false;
  try {
    while (!streamEnded) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";
      blocks.forEach(consumeBlock);
      if (done) streamEnded = true;
    }
    if (buffer.trim()) consumeBlock(buffer);
  } finally {
    reader.releaseLock();
  }
}

async function stream(
  path: string,
  body: ChatRequest | ResumeRequest,
  onEvent: (event: WorkflowEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  await consumeSseStream(response, onEvent);
}

export const chatService = {
  sessions: () =>
    collectPages((page) =>
      apiRequest<PaginatedResponse<ChatSession>>(
        `/api/v1/chat/sessions?page=${page}&size=100`,
      ),
    ),
  messages: (threadId: string) =>
    collectPages((page) =>
      apiRequest<PaginatedResponse<PersistedChatMessage>>(
        `/api/v1/chat/sessions/${encodeURIComponent(threadId)}/messages?page=${page}&size=100`,
      ),
    ),
  send: (
    request: ChatRequest,
    onEvent: (event: WorkflowEvent) => void,
    signal?: AbortSignal,
  ) => stream("/api/v1/chat/stream", request, onEvent, signal),
  resume: (
    request: ResumeRequest,
    onEvent: (event: WorkflowEvent) => void,
    signal?: AbortSignal,
  ) => stream("/api/v1/chat/resume", request, onEvent, signal),
  state: (threadId: string) =>
    apiRequest<SessionState>(
      `/api/v1/chat/sessions/${encodeURIComponent(threadId)}/state`,
    ),
};
