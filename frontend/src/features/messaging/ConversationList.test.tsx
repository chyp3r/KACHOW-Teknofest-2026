import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConversationList } from "./ConversationList";
import type { Conversation } from "../../types/messaging";

function dm(id: string, unread: number): Conversation {
  return {
    id,
    kind: "dm",
    title: null,
    last_message_at: "2026-08-16T10:00:00Z",
    is_archived: false,
    created_at: "2026-08-16T10:00:00Z",
    participants: [
      { user_id: "me", username: "ben", role_in_conversation: "member", joined_at: "2026-08-16T10:00:00Z", left_at: null },
      { user_id: "other", username: "Ahmet Yılmaz", role_in_conversation: "member", joined_at: "2026-08-16T10:00:00Z", left_at: null },
    ],
    unread_count: unread,
    role_in_conversation: "member",
  };
}

describe("ConversationList", () => {
  it("shows the other participant's username as a DM's title, not the caller's own", () => {
    render(
      <ConversationList
        conversations={[dm("conv-1", 0)]}
        currentUserId="me"
        loading={false}
        onSelect={vi.fn()}
        onNewConversation={vi.fn()}
        onOpenPeople={vi.fn()}
      />,
    );
    expect(screen.getByText("Ahmet Yılmaz")).toBeInTheDocument();
    expect(screen.queryByText("ben")).not.toBeInTheDocument();
  });

  it("renders an unread badge only when unread_count is positive", () => {
    render(
      <ConversationList
        conversations={[dm("conv-1", 3), dm("conv-2", 0)]}
        currentUserId="me"
        loading={false}
        onSelect={vi.fn()}
        onNewConversation={vi.fn()}
        onOpenPeople={vi.fn()}
      />,
    );
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("calls onSelect with the clicked conversation's id", () => {
    const onSelect = vi.fn();
    render(
      <ConversationList
        conversations={[dm("conv-1", 0)]}
        currentUserId="me"
        loading={false}
        onSelect={onSelect}
        onNewConversation={vi.fn()}
        onOpenPeople={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Ahmet Yılmaz"));
    expect(onSelect).toHaveBeenCalledWith("conv-1");
  });

  it("shows an empty state with no conversations", () => {
    render(
      <ConversationList
        conversations={[]}
        currentUserId="me"
        loading={false}
        onSelect={vi.fn()}
        onNewConversation={vi.fn()}
        onOpenPeople={vi.fn()}
      />,
    );
    expect(screen.getByText("Henüz konuşmanız yok")).toBeInTheDocument();
  });
});
