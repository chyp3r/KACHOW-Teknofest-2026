import { apiFetch } from "./apiClient";

/**
 * Minimal SSE reader for the "one JSON value per `data:` frame" streams
 * (`/messaging/stream`, `/notifications/stream`) -- distinct from
 * `chatService.consumeSseStream`, which additionally validates each frame
 * against the structured `WorkflowEvent` union. These two streams carry no
 * such envelope: a frame is either the handshake (`{"event":"connected"}`),
 * an error (`{"event":"error", "message": string}`), or the raw resource
 * payload itself (a `Message` or a `Notification`).
 */
export async function readRawSseStream(
  response: Response,
  onData: (value: unknown) => void,
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Sunucu akış yanıtı göndermedi.");

  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  const consumeBlock = (block: string) => {
    const raw = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n")
      .trim();
    if (!raw) return;
    try {
      const value = JSON.parse(raw);
      if (
        typeof value === "object" &&
        value !== null &&
        "event" in value &&
        (value.event === "connected" || value.event === "error")
      ) {
        return;
      }
      onData(value);
    } catch {
      // Not JSON (a keep-alive comment line already filtered above, or a
      // malformed frame) -- ignored rather than throwing, same as
      // consumeSseStream's own tolerance for a stray frame.
    }
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

/**
 * Open a live SSE connection and call `onData` for every real payload
 * frame. Returns a cleanup function that aborts the underlying fetch --
 * call it on unmount, same lifecycle every other subscription in this
 * codebase follows.
 */
export function subscribeToRawStream(
  path: string,
  onData: (value: unknown) => void,
): () => void {
  const controller = new AbortController();
  void (async () => {
    try {
      const response = await apiFetch(path, { signal: controller.signal });
      if (!response.ok) return;
      await readRawSseStream(response, onData);
    } catch (error) {
      if (controller.signal.aborted) return;
      // A dropped stream is never data loss for either consumer (see
      // messaging_channel_for/channel_for's own docstrings) -- the caller's
      // own query cache is the source of truth, this is only the live push.
      console.warn("SSE stream'i sonlandı:", error);
    }
  })();
  return () => controller.abort();
}
