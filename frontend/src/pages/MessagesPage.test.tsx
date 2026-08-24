import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MessagesPage } from "./MessagesPage";

const mocks = vi.hoisted(() => ({
  markRead: vi.fn().mockResolvedValue(undefined),
  unreadCount: 0,
}));

vi.mock("../features/messaging/ConversationList", () => ({
  ConversationList: () => <div data-testid="conversation-list">Konuşmalar</div>,
}));
vi.mock("../features/messaging/MessageThread", () => ({
  MessageThread: () => <div>Mesaj akışı</div>,
}));
vi.mock("../features/messaging/MessageComposer", () => ({
  MessageComposer: () => <div>Mesaj alanı</div>,
}));
vi.mock("../features/messaging/NewConversationDialog", () => ({
  NewConversationDialog: () => null,
}));
vi.mock("../features/messaging/SendArtifactDialog", () => ({
  SendArtifactDialog: () => null,
}));
vi.mock("../features/messaging/UserSearchDrawer", () => ({
  UserSearchDrawer: () => null,
}));
vi.mock("../features/messaging/GroupParticipantsPanel", () => ({
  GroupParticipantsPanel: () => null,
}));

vi.mock("../hooks/useConversations", () => ({
  useConversations: () => ({
    conversations: [
      {
        id: "conversation-1",
        kind: "dm",
        unread_count: mocks.unreadCount,
        last_message_at: "2026-08-20T10:00:00Z",
        participants: [
          { user_id: "employee-1", username: "employee", left_at: null },
          { user_id: "employee-2", username: "colleague", left_at: null },
        ],
      },
    ],
    errorObject: null,
    loading: false,
    creatingGroup: false,
    openDm: vi.fn(),
    createGroup: vi.fn(),
    addParticipants: vi.fn(),
    removeParticipant: vi.fn(),
  }),
}));

vi.mock("../hooks/useMessageThread", () => ({
  useMessageThread: () => ({
    messages: [],
    loading: false,
    loadingOlder: false,
    hasMore: false,
    sending: false,
    errorObject: null,
    markRead: mocks.markRead,
    loadOlder: vi.fn(),
    send: vi.fn(),
  }),
}));

function renderPage(activeConversationId?: string, onCloseConversation = vi.fn()) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MessagesPage
        currentUserId="employee-1"
        activeConversationId={activeConversationId}
        onSelectConversation={vi.fn()}
        onCloseConversation={onCloseConversation}
      />
    </QueryClientProvider>,
  );
}

describe("MessagesPage responsive conversation navigation", () => {
  beforeEach(() => {
    mocks.unreadCount = 0;
    mocks.markRead.mockClear();
  });

  it("marks an active thread so mobile CSS can switch from the list to the thread", () => {
    renderPage("conversation-1");

    expect(screen.getByTestId("conversation-list").parentElement).toHaveClass(
      "has-active-conversation",
    );
    expect(screen.getByRole("heading", { name: "colleague" })).toBeInTheDocument();
  });

  it("provides a mobile back action for returning to the conversation list", () => {
    const onCloseConversation = vi.fn();
    renderPage("conversation-1", onCloseConversation);

    fireEvent.click(screen.getByRole("button", { name: "Konuşma listesine dön" }));

    expect(onCloseConversation).toHaveBeenCalledOnce();
  });

  it("marks incoming unread messages as read when their thread is visible", async () => {
    mocks.unreadCount = 2;

    renderPage("conversation-1");

    await waitFor(() => expect(mocks.markRead).toHaveBeenCalledOnce());
  });
});
