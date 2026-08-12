import { render, screen } from "@testing-library/react";
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

describe("MessageList", () => {
  it("renders a pending draft approval as a chat bubble in the scrolling conversation, not a standalone panel", () => {
    const interrupt: InterruptState = {
      kind: "draft_approval",
      interruptId: "interrupt-1",
      payload: { draft: "Onaylanacak taslak metni" },
    };
    const { container } = render(
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
    expect(screen.getByRole("button", { name: "Onayla" })).toBeInTheDocument();
  });

  it("does not show the empty state when a fresh session already has a pending interrupt", () => {
    const interrupt: InterruptState = {
      kind: "missing_information",
      interruptId: "interrupt-2",
      payload: { questions: [] },
    };
    render(
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
    const { container } = render(<MessageList {...baseProps} messages={[{ sender: "assistant", text: "tamam" }]} />);
    expect(container.querySelector(".interrupt-message")).toBeNull();
  });
});
