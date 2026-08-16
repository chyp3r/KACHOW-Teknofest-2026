import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useConversations } from "./useConversations";
import type { Conversation } from "../types/messaging";

const mocks = vi.hoisted(() => ({
  conversations: vi.fn(),
  openDm: vi.fn(),
  createGroup: vi.fn(),
  updateConversation: vi.fn(),
  addParticipants: vi.fn(),
  removeParticipant: vi.fn(),
  conversation: vi.fn(),
}));

vi.mock("../services/messagingService", () => ({ messagingService: mocks }));

function dm(id: string, unread: number, lastMessageAt: string | null): Conversation {
  return {
    id,
    kind: "dm",
    title: null,
    last_message_at: lastMessageAt,
    is_archived: false,
    created_at: "2026-08-16T10:00:00Z",
    participants: [
      { user_id: "me", username: "ben", role_in_conversation: "member", joined_at: "2026-08-16T10:00:00Z", left_at: null },
      { user_id: "other", username: "diğer", role_in_conversation: "member", joined_at: "2026-08-16T10:00:00Z", left_at: null },
    ],
    unread_count: unread,
    role_in_conversation: "member",
  };
}

describe("useConversations", () => {
  function wrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, {
      client: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
    }, children);
  }

  beforeEach(() => {
    mocks.conversations.mockReset().mockResolvedValue({
      items: [dm("conv-1", 2, "2026-08-16T10:00:00Z"), dm("conv-2", 0, "2026-08-16T09:00:00Z")],
      total: 2, page: 1, size: 50, pages: 1,
    });
    mocks.openDm.mockReset();
    mocks.createGroup.mockReset();
    mocks.addParticipants.mockReset();
    mocks.removeParticipant.mockReset();
    mocks.conversation.mockReset();
  });

  it("sums unread_count across every conversation", async () => {
    const { result } = renderHook(() => useConversations(), { wrapper });
    await waitFor(() => expect(result.current.conversations).toHaveLength(2));
    expect(result.current.unreadTotal).toBe(2);
  });

  it("opening an already-open DM upserts in place rather than duplicating it", async () => {
    const { result } = renderHook(() => useConversations(), { wrapper });
    await waitFor(() => expect(result.current.conversations).toHaveLength(2));

    const reopened = dm("conv-2", 0, "2026-08-16T11:30:00Z");
    mocks.openDm.mockResolvedValue(reopened);

    await act(async () => {
      await result.current.openDm("other");
    });

    // The reopened conversation moves to the front -- its last_message_at
    // is now the most recent. `mutateAsync` resolving doesn't guarantee the
    // cache-write side effect has already propagated to this render, so
    // assert via waitFor rather than immediately after act().
    await waitFor(() => expect(result.current.conversations[0].id).toBe("conv-2"));
    expect(result.current.conversations).toHaveLength(2);
  });

  it("creating a group adds a new conversation without touching existing ones", async () => {
    const { result } = renderHook(() => useConversations(), { wrapper });
    await waitFor(() => expect(result.current.conversations).toHaveLength(2));

    const created: Conversation = {
      ...dm("conv-3", 0, "2026-08-16T12:00:00Z"),
      kind: "group",
      title: "Proje",
      role_in_conversation: "owner",
    };
    mocks.createGroup.mockResolvedValue(created);

    await act(async () => {
      await result.current.createGroup("Proje", ["other"]);
    });

    await waitFor(() =>
      expect(result.current.conversations.map((item) => item.id)).toContain("conv-3"),
    );
    expect(result.current.conversations).toHaveLength(3);
  });
});
