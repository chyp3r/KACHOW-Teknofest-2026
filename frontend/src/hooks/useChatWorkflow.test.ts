import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useChatWorkflow } from "./useChatWorkflow";

const mocks = vi.hoisted(() => ({
  send: vi.fn(),
  resume: vi.fn(),
  state: vi.fn(),
}));

vi.mock("../services/chatService", () => ({ chatService: mocks }));

describe("useChatWorkflow", () => {
  beforeEach(() => {
    localStorage.clear();
    mocks.send.mockReset();
    mocks.resume.mockReset();
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
    const { result } = renderHook(() => useChatWorkflow(null, "user-1"));

    await act(() => result.current.send("ilk", "balanced", false));
    await act(() => result.current.send("ikinci", "balanced", false));

    const firstSession = mocks.send.mock.calls[0][0].session_id as string;
    const secondSession = mocks.send.mock.calls[1][0].session_id as string;
    expect(firstSession).toMatch(/^web:/);
    expect(secondSession).toBe(firstSession);
    expect(secondSession).not.toContain("user-1:");
  });

  it("recovers a pending interrupt after reload", async () => {
    localStorage.setItem(
      "kachow.chat.session.user-1",
      JSON.stringify({
        clientSessionId: "web:client",
        threadId: "user-1:web:client",
      }),
    );
    mocks.state.mockResolvedValue({
      status: "interrupted",
      interrupt: {
        kind: "missing_information",
        questions: [{ key: "muhatap", label: "Muhatap", required: true }],
      },
    });

    const { result } = renderHook(() => useChatWorkflow(null, "user-1"));

    await waitFor(() =>
      expect(result.current.pendingInterrupt?.kind).toBe("missing_information"),
    );
    expect(mocks.state).toHaveBeenCalledWith("user-1:web:client");
  });
});
