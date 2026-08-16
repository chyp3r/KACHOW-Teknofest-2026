import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";

const setMode = vi.fn();

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({
    user: {
      id: "employee-1",
      username: "employee",
      email: "employee@example.test",
      role: "employee",
      clearance_level: "hizmete_ozel",
      is_active: true,
      is_deleted: false,
    },
    logout: vi.fn(),
  }),
}));

vi.mock("../hooks/useTheme", () => ({
  useTheme: () => ({ mode: "system", setMode }),
}));

// AppShell now mounts useConversations (sidebar unread badge) and
// NotificationBell (useNotifications/useNotificationsStream) -- both need
// a QueryClientProvider ancestor, same wrapper `useDocuments.test.ts` uses.
function withQueryClient(children: ReactNode) {
  return createElement(
    QueryClientProvider,
    { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
    children,
  );
}

describe("AppShell compact navigation", () => {
  beforeEach(() => {
    localStorage.clear();
    setMode.mockReset();
  });

  it("always exposes a keyboard-accessible way to expand a persisted compact sidebar", () => {
    localStorage.setItem("kachow.sidebar.compact", "true");
    render(
      withQueryClient(
        <MemoryRouter initialEntries={["/chats"]}>
          <AppShell><div>İçerik</div></AppShell>
        </MemoryRouter>,
      ),
    );

    const expand = screen.getByRole("button", { name: "Menüyü genişlet" });
    expect(expand).toHaveAttribute("aria-controls", "primary-sidebar");
    expect(expand).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(expand);

    expect(screen.getByRole("button", { name: "Menüyü daralt" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(localStorage.getItem("kachow.sidebar.compact")).toBe("false");
  });

  it("removes the mobile trigger while the navigation drawer is open", () => {
    render(
      withQueryClient(
        <MemoryRouter initialEntries={["/chats"]}>
          <AppShell><div>İçerik</div></AppShell>
        </MemoryRouter>,
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Menüyü aç" }));

    expect(screen.queryByRole("button", { name: "Menüyü aç" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Menüyü kapat" })).not.toHaveLength(0);
  });

  it("does not render a duplicate standalone theme control while expanded", () => {
    render(
      withQueryClient(
        <MemoryRouter initialEntries={["/chats"]}>
          <AppShell><div>İçerik</div></AppShell>
        </MemoryRouter>,
      ),
    );

    expect(screen.getByRole("combobox", { name: "Tema seçimi" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Tema: system/ })).not.toBeInTheDocument();
  });
});
