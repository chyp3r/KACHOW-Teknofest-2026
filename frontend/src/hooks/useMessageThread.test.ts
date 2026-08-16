import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useMessageThread } from "./useMessageThread";
import type { Message } from "../types/messaging";

const mocks = vi.hoisted(() => ({
  messages: vi.fn(),
  sendMessage: vi.fn(),
  markRead: vi.fn(),
}));

vi.mock("../services/messagingService", () => ({ messagingService: mocks }));

function message(id: string, createdAt: string, body = "merhaba"): Message {
  return {
    id,
    conversation_id: "conv-1",
    sender_id: "other",
    sender_username: "diğer",
    kind: "text",
    body,
    artifact_transfer_id: null,
    created_at: createdAt,
  };
}

describe("useMessageThread", () => {
  function wrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, {
      client: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
    }, children);
  }

  beforeEach(() => {
    mocks.messages.mockReset();
    mocks.sendMessage.mockReset();
    mocks.markRead.mockReset();
  });

  it("reverses the backend's newest-first page into chronological order", async () => {
    // The backend returns newest-first (see messagingService.messages'
    // own docstring convention); the hook must present oldest-first so the
    // thread reads top-to-bottom like every other list in this app.
    mocks.messages.mockResolvedValue([
      message("msg-3", "2026-08-16T10:02:00Z"),
      message("msg-2", "2026-08-16T10:01:00Z"),
      message("msg-1", "2026-08-16T10:00:00Z"),
    ]);

    const { result } = renderHook(() => useMessageThread("conv-1"), { wrapper });

    await waitFor(() => expect(result.current.messages).toHaveLength(3));
    expect(result.current.messages.map((item) => item.id)).toEqual(["msg-1", "msg-2", "msg-3"]);
  });

  it("prepends an older page fetched via loadOlder", async () => {
    // A full 50-row page is what tells the hook "there might be more" --
    // see useMessageThread's own `hasMore` computation (`page.length ===
    // PAGE_SIZE`). A short first page (fewer than 50) legitimately means
    // "that's everything", so `loadOlder` must have something to load from.
    const firstPage = Array.from({ length: 50 }, (_, index) =>
      message(`msg-${50 - index}`, `2026-08-16T10:${String(50 - index).padStart(2, "0")}:00Z`),
    );
    mocks.messages.mockResolvedValueOnce(firstPage);
    const { result } = renderHook(() => useMessageThread("conv-1"), { wrapper });
    await waitFor(() => expect(result.current.messages).toHaveLength(50));
    expect(result.current.hasMore).toBe(true);

    mocks.messages.mockResolvedValueOnce([message("msg-0", "2026-08-16T09:59:00Z")]);
    await act(async () => {
      await result.current.loadOlder();
    });

    await waitFor(() => expect(result.current.messages).toHaveLength(51));
    expect(result.current.messages[0].id).toBe("msg-0");
    expect(mocks.messages).toHaveBeenLastCalledWith("conv-1", "msg-1", 50);
  });

  it("sending a message appends it to the end of the thread", async () => {
    mocks.messages.mockResolvedValue([message("msg-1", "2026-08-16T10:00:00Z")]);
    const { result } = renderHook(() => useMessageThread("conv-1"), { wrapper });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));

    const sent = message("msg-2", "2026-08-16T10:05:00Z", "yeni mesaj");
    sent.sender_id = "me";
    mocks.sendMessage.mockResolvedValue(sent);

    await act(async () => {
      await result.current.send("yeni mesaj");
    });

    await waitFor(() =>
      expect(result.current.messages.map((item) => item.id)).toEqual(["msg-1", "msg-2"]),
    );
  });
});
