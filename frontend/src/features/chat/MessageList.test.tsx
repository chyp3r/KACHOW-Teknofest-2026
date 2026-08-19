import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import type { ChatMessage, InterruptState } from "../../types/chat";
import { MessageList } from "./MessageList";

const baseProps = {
  messages: [] as ChatMessage[],
  streamingText: "",
  loading: false,
  logs: [],
  hasSelectedDocument: false,
  onSuggestion: vi.fn(),
};

// A message.sender === "assistant" message renders FeedbackButtons (Faz
// C1), which calls useMutation -- every render in this file needs a
// QueryClient in scope now, same as AdminPage.test.tsx's own wrapper.
function renderWithQueryClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("MessageList", () => {
  it("renders a pending missing-information gate as a chat bubble in the scrolling conversation, not a standalone panel", () => {
    const interrupt: InterruptState = {
      kind: "missing_information",
      interruptId: "interrupt-1",
      payload: {
        draft: "Onaylanacak taslak metni",
        questions: [
          {
            key: "muhatap",
            question: "'Muhatap' bilgisi nedir?",
            header: "Muhatap",
            options: [],
            multi_select: false,
            allow_free_text: true,
            required: true,
          },
        ],
      },
    };
    const { container } = renderWithQueryClient(
      <MessageList
        {...baseProps}
        messages={[{ sender: "user", text: "taslak hazırla" }]}
        interrupt={interrupt}
        onResume={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    // Lives inside .messages-area as a .chat-message article, the same
    // container every ordinary message scrolls in -- not a sibling panel
    // pinned above it (the old .interrupt-panel standalone-card layout).
    const bubble = container.querySelector(".chat-message.interrupt-message");
    expect(bubble).not.toBeNull();
    expect(bubble?.closest(".messages-area")).not.toBeNull();
    expect(screen.getByText("Onaylanacak taslak metni")).toBeInTheDocument();
    expect(screen.getByText("Birkaç bilgi daha gerekiyor")).toBeInTheDocument();
  });

  it("does not show the empty state when a fresh session already has a pending interrupt", () => {
    const interrupt: InterruptState = {
      kind: "missing_information",
      interruptId: "interrupt-2",
      payload: { questions: [] },
    };
    renderWithQueryClient(
      <MessageList
        {...baseProps}
        messages={[]}
        interrupt={interrupt}
        onResume={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.queryByText("Nasıl yardımcı olabilirim?")).not.toBeInTheDocument();
  });

  it("renders no interrupt bubble when there is nothing pending", () => {
    const { container } = renderWithQueryClient(
      <MessageList {...baseProps} messages={[{ sender: "assistant", text: "tamam" }]} />,
    );
    expect(container.querySelector(".interrupt-message")).toBeNull();
  });

  it("offers a 👍/👎 vote on an assistant reply but not on the user's own message", () => {
    renderWithQueryClient(
      <MessageList
        {...baseProps}
        messages={[
          { sender: "user", text: "taslak hazırla" },
          { sender: "assistant", text: "İşte taslağınız." },
        ]}
      />,
    );

    expect(screen.getAllByRole("button", { name: "Beğendim" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Beğenmedim" })).toHaveLength(1);
  });

  it("does not offer a vote on a non-blocking notice message", () => {
    renderWithQueryClient(
      <MessageList
        {...baseProps}
        messages={[{ sender: "assistant", text: "Bir çelişki bulundu.", kind: "notice" }]}
      />,
    );

    expect(screen.queryByRole("button", { name: "Beğendim" })).not.toBeInTheDocument();
  });
});
