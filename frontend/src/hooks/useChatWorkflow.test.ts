import { createElement, useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useChatWorkflow } from "./useChatWorkflow";

const mocks = vi.hoisted(() => ({
  send: vi.fn(),
  resume: vi.fn(),
  state: vi.fn(),
  sessions: vi.fn(),
  messages: vi.fn(),
}));

vi.mock("../services/chatService", () => ({ chatService: mocks }));

describe("useChatWorkflow", () => {
  function wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    return createElement(QueryClientProvider, { client }, children);
  }

  beforeEach(() => {
    mocks.send.mockReset();
    mocks.resume.mockReset();
    mocks.sessions.mockReset().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
    mocks.messages.mockReset().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 });
    mocks.state.mockReset().mockResolvedValue({ status: "idle", interrupt: null });
    mocks.send.mockImplementation(async (_request, onEvent) => {
      onEvent({ event: "session", thread_id: "user-1:web:thread" });
      onEvent({
        event: "final_result",
        reply: "tamam",
        workflow_status: "COMPLETED",
      });
    });
  });

  it("keeps the client session id separate from the prefixed backend thread id", async () => {
    const onSessionResolved = vi.fn();
    const { result } = renderHook(
      () => useChatWorkflow(null, "user-1", null, onSessionResolved),
      { wrapper },
    );

    await act(() => result.current.send("ilk", "balanced", false));
    await act(() => result.current.send("ikinci", "balanced", false));

    const firstSession = mocks.send.mock.calls[0][0].session_id as string;
    const secondSession = mocks.send.mock.calls[1][0].session_id as string;
    expect(firstSession).toMatch(/^web:/);
    expect(secondSession).toBe(firstSession);
    expect(secondSession).not.toContain("user-1:");
    expect(onSessionResolved).toHaveBeenCalledWith("user-1:web:thread");
  });

  it("preserves the active stream when the first session event updates the route", async () => {
    let continueStream: (() => void) | undefined;
    let receivedSignal: AbortSignal | undefined;
    mocks.send.mockImplementation(async (_request, onEvent, signal: AbortSignal) => {
      receivedSignal = signal;
      onEvent({ event: "session", thread_id: "user-1:web:resolved" });
      await new Promise<void>((resolve) => {
        continueStream = resolve;
      });
      if (signal.aborted) throw new DOMException("cancelled", "AbortError");
      onEvent({
        event: "final_result",
        reply: "Yanıt korundu",
        workflow_status: "COMPLETED",
      });
    });

    const { result } = renderHook(() => {
      const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
      const workflow = useChatWorkflow(
        null,
        "user-1",
        activeSessionId,
        setActiveSessionId,
      );
      return { activeSessionId, workflow };
    }, { wrapper });

    let pending!: Promise<void>;
    act(() => {
      pending = result.current.workflow.send("İlk mesaj", "balanced", false);
    });

    await waitFor(() =>
      expect(result.current.activeSessionId).toBe("user-1:web:resolved"),
    );
    expect(receivedSignal?.aborted).toBe(false);
    expect(result.current.workflow.messages).toEqual([
      { sender: "user", text: "İlk mesaj" },
    ]);

    await act(async () => {
      continueStream?.();
      await pending;
    });

    expect(receivedSignal?.aborted).toBe(false);
    expect(result.current.workflow.messages.map((message) => message.text)).toEqual([
      "İlk mesaj",
      "Yanıt korundu",
    ]);
  });

  it("recovers persisted messages and a pending interrupt from the server", async () => {
    mocks.messages.mockResolvedValue({
      items: [{
        id: "message-1",
        role: "assistant",
        content: "Önceki yanıt",
        workflow_status: "INTERRUPTED",
        details: null,
        created_at: "2026-08-09T10:00:00Z",
      }],
      total: 1,
      page: 1,
      page_size: 50,
    });
    mocks.state.mockResolvedValue({
      status: "interrupted",
      interrupt: {
        kind: "missing_information",
        questions: [{ key: "muhatap", label: "Muhatap", required: true }],
      },
    });

    const { result } = renderHook(
      () => useChatWorkflow(null, "user-1", "user-1:web:client"),
      { wrapper },
    );

    await waitFor(() =>
      expect(result.current.pendingInterrupt?.kind).toBe("missing_information"),
    );
    expect(result.current.messages[0]?.text).toBe("Önceki yanıt");
    expect(mocks.messages).toHaveBeenCalledWith("user-1:web:client");
    expect(mocks.state).toHaveBeenCalledWith("user-1:web:client");
  });

  it("aborts an active stream without rendering a workflow failure", async () => {
    let receivedSignal: AbortSignal | undefined;
    mocks.send.mockImplementation((_request, _onEvent, signal: AbortSignal) => {
      receivedSignal = signal;
      return new Promise<void>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("cancelled", "AbortError")));
      });
    });
    const { result } = renderHook(() => useChatWorkflow(null, "user-1"), { wrapper });

    let pending!: Promise<void>;
    act(() => { pending = result.current.send("iptal et", "balanced", false); });
    await waitFor(() => expect(result.current.loading).toBe(true));
    act(() => result.current.cancel());
    await act(async () => pending);

    expect(receivedSignal?.aborted).toBe(true);
    expect(result.current.messages).toEqual([{ sender: "user", text: "iptal et" }]);
  });
});
