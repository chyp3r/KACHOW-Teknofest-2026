import { authorizedHeaders } from "./apiClient";
import type { ChatRequest, ResumeRequest, WorkflowEvent } from "../types/chat";

async function consumeStream(
  response: Response,
  onEvent: (event: WorkflowEvent) => void,
): Promise<void> {
  if (!response.ok) throw new Error("Sohbet akışı başlatılamadı.");
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Sunucu akış yanıtı göndermedi.");
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let streamEnded = false;
  while (!streamEnded) {
    const { value, done } = await reader.read();
    if (done) {
      streamEnded = true;
      continue;
    }
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      if (!block.startsWith("data: ")) continue;
      const raw = block.slice(6).trim();
      if (!raw || raw === "[DONE]") continue;
      onEvent(JSON.parse(raw) as WorkflowEvent);
    }
  }
}

async function stream(
  path: string,
  body: ChatRequest | ResumeRequest,
  onEvent: (event: WorkflowEvent) => void,
) {
  const response = await fetch(path, {
    method: "POST",
    headers: authorizedHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  return consumeStream(response, onEvent);
}

export const chatService = {
  send: (request: ChatRequest, onEvent: (event: WorkflowEvent) => void) =>
    stream("/api/v1/chat/stream", request, onEvent),
  resume: (request: ResumeRequest, onEvent: (event: WorkflowEvent) => void) =>
    stream("/api/v1/chat/resume", request, onEvent),
};
