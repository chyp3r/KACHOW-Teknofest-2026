import { createRef, useRef, useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ChatSession } from "../../types/chat";
import { ConversationHistoryDrawer } from "./ConversationHistoryDrawer";

function timestamp(daysAgo: number, hour = 10): string {
  const value = new Date();
  value.setDate(value.getDate() - daysAgo);
  value.setHours(hour, 0, 0, 0);
  return value.toISOString();
}

function session(
  id: string,
  title: string,
  daysAgo: number,
): ChatSession {
  return {
    session_id: id,
    title,
    document_id: null,
    created_at: timestamp(daysAgo, 9),
    updated_at: timestamp(daysAgo, 10),
  };
}

const baseProps = {
  sessions: [] as ChatSession[],
  activeSessionId: null,
  loading: false,
  refreshing: false,
  error: null,
  returnFocusRef: createRef<HTMLButtonElement>(),
  onClose: vi.fn(),
  onRetry: vi.fn().mockResolvedValue(undefined),
  onNewChat: vi.fn(),
  onOpenSession: vi.fn(),
};

describe("ConversationHistoryDrawer", () => {
  it("keeps loading, error, and empty states mutually exclusive", () => {
    const { container, rerender } = render(
      <ConversationHistoryDrawer {...baseProps} loading />,
    );
    expect(screen.getByRole("status", { name: "Sohbet geçmişi yükleniyor" })).toBeInTheDocument();
    expect(container.querySelectorAll(".chat-history-skeleton")).toHaveLength(4);
    expect(screen.queryByText("Henüz kayıtlı sohbetiniz yok")).not.toBeInTheDocument();

    rerender(
      <ConversationHistoryDrawer
        {...baseProps}
        error="Sohbet geçmişi alınamadı."
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Sohbet geçmişi alınamadı.");
    expect(screen.getByRole("button", { name: "Tekrar dene" })).toBeInTheDocument();
    expect(screen.queryByText("Henüz kayıtlı sohbetiniz yok")).not.toBeInTheDocument();

    rerender(<ConversationHistoryDrawer {...baseProps} />);
    expect(screen.getByText("Henüz kayıtlı sohbetiniz yok")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Yeni sohbet başlat" })).toBeInTheDocument();
  });

  it("groups successful rows, preserves them while refreshing, and marks the active session", () => {
    render(
      <ConversationHistoryDrawer
        {...baseProps}
        sessions={[
          session("today", "Bugünkü görüşme", 0),
          session("yesterday", "Dünkü görüşme", 1),
          session("older", "Eski görüşme", 5),
        ]}
        activeSessionId="today"
        refreshing
      />,
    );

    expect(screen.getByRole("heading", { name: "Bugün" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Dün" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Daha eski" })).toBeInTheDocument();
    // The row shows only the session title (the user's first message) -- no
    // assistant-reply preview line.
    expect(screen.getByRole("button", { name: /Bugünkü görüşme/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByText("Güncelleniyor")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Sohbetlerde ara")).not.toBeInTheDocument();
  });

  it("adds search only when the list is large enough", () => {
    const sessions = Array.from({ length: 10 }, (_, index) =>
      session(`session-${index}`, `Görüşme ${index}`, index % 3),
    );
    render(<ConversationHistoryDrawer {...baseProps} sessions={sessions} />);

    const search = screen.getByPlaceholderText("Sohbetlerde ara");
    fireEvent.change(search, { target: { value: "Görüşme 9" } });
    expect(screen.getByText("Görüşme 9")).toBeInTheDocument();
    expect(screen.queryByText("Görüşme 1")).not.toBeInTheDocument();
  });

  it("locks scrolling, traps focus, closes with Escape, and restores trigger focus", () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      const triggerRef = useRef<HTMLButtonElement>(null);
      return (
        <>
          <button ref={triggerRef} onClick={() => setOpen(true)}>Geçmişi aç</button>
          {open && (
            <ConversationHistoryDrawer
              {...baseProps}
              returnFocusRef={triggerRef}
              onClose={() => setOpen(false)}
            />
          )}
        </>
      );
    }

    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Geçmişi aç" });
    fireEvent.click(trigger);

    const close = screen.getAllByRole("button", { name: "Sohbet geçmişini kapat" })[1];
    const newChat = screen.getByRole("button", { name: "Yeni sohbet başlat" });
    expect(close).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");

    newChat.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(close).toHaveFocus();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Sohbet geçmişi" })).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe("");
    expect(trigger).toHaveFocus();

    fireEvent.click(trigger);
    fireEvent.click(
      screen.getAllByRole("button", { name: "Sohbet geçmişini kapat" })[0],
    );
    expect(screen.queryByRole("dialog", { name: "Sohbet geçmişi" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
