import { apiErrorFromResponse, apiFetch, apiRequest } from "./apiClient";
import type {
  ChatRequest,
  ResumeRequest,
  SessionState,
  WorkflowEvent,
} from "../types/chat";

export async function consumeSseStream(
  response: Response,
  onEvent: (event: WorkflowEvent) => void,
): Promise<void> {
  if (!response.ok) throw await apiErrorFromResponse(response);
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Sunucu akış yanıtı göndermedi.");

  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let lastSequence = 0;

  const consumeBlock = (block: string) => {
    const raw = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n")
      .trim();
    if (!raw || raw === "[DONE]") return;
    const event = JSON.parse(raw) as WorkflowEvent;
    if (event.seq !== undefined) {
      if (event.seq <= lastSequence) return;
      lastSequence = event.seq;
    }
    onEvent(event);
  };

  let streamEnded = false;
  while (!streamEnded) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    blocks.forEach(consumeBlock);
    if (done) streamEnded = true;
  }
  if (buffer.trim()) consumeBlock(buffer);
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
