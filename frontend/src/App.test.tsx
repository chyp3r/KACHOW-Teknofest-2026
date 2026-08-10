import type { ReactNode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

const state = vi.hoisted(() => ({
  user: null as null | {
    id: string; username: string; email: string; role: "employee";
    clearance_level: "hizmete_ozel"; is_active: boolean; is_deleted: boolean;
  },
}));

vi.mock("./hooks/useAuth", () => ({ useAuth: () => ({
  user: state.user, loading: false, login: vi.fn(), logout: vi.fn(),
}) }));
vi.mock("./hooks/useDocuments", () => ({ useDocuments: () => ({
  documents: [], selectedDocument: null, analysis: null, loading: false,
  uploading: false, error: null, setSelectedDocument: vi.fn(), upload: vi.fn(),
}) }));
vi.mock("./hooks/useChatWorkflow", () => ({ useChatWorkflow: () => ({
  sessions: [], sessionsLoading: false, sessionsRefreshing: false, sessionsError: null,
  historyLoading: false, historyError: null,
  messages: [], loading: false, streamingText: "", pendingInterrupt: null,
  nodeStatus: {}, nodeResults: {}, nodeMeta: {}, planSteps: [], logs: [],
  toolCalls: [], guardrailEvents: [], send: vi.fn(), resume: vi.fn(), newChat: vi.fn(),
  cancel: vi.fn(), addUploadMessage: vi.fn(), retrySessions: vi.fn(), retryHistory: vi.fn(),
}) }));
vi.mock("./layouts/AppShell", () => ({ AppShell: ({ children }: { children: ReactNode }) => <div>{children}</div> }));
vi.mock("./features/documents/DocumentLibraryPanel", () => ({ DocumentLibraryPanel: () => null }));
vi.mock("./features/chat/DecisionFlow", () => ({ DecisionFlow: () => null }));
vi.mock("./pages/LoginPage", () => ({ LoginPage: () => <h1>Login screen</h1> }));
vi.mock("./pages/ChatsPage", () => ({ ChatsPage: () => <h1>Chats screen</h1> }));
vi.mock("./pages/AdminPage", () => ({ AdminPage: () => <h1>Admin screen</h1> }));

function LocationProbe() {
  return <output>{useLocation().pathname}</output>;
}

describe("application route guards", () => {
  it("redirects a direct chat deep link to login when unauthenticated", async () => {
    state.user = null;
    render(<MemoryRouter initialEntries={["/chats/user:web:one"]}><App /><LocationProbe /></MemoryRouter>);

    expect(await screen.findByText("Login screen")).toBeInTheDocument();
    expect(screen.getByText("/login")).toBeInTheDocument();
  });

  it("redirects an employee away from the admin route", async () => {
    state.user = {
      id: "employee-1", username: "employee", email: "employee@example.test",
      role: "employee", clearance_level: "hizmete_ozel", is_active: true, is_deleted: false,
    };
    render(<MemoryRouter initialEntries={["/admin"]}><App /><LocationProbe /></MemoryRouter>);

    await waitFor(() => expect(screen.getByText("/chats")).toBeInTheDocument());
    expect(screen.queryByText("Admin screen")).not.toBeInTheDocument();
  });
});
