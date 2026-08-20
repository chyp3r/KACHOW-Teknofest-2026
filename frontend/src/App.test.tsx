import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const state = vi.hoisted(() => ({
  user: null as null | {
    id: string; username: string; email: string; role: "employee";
    clearance_level: "hizmete_ozel"; is_active: boolean; is_deleted: boolean;
  },
  selectedDocument: null as null | {
    file_name: string; storage_path: string; upload_time: string;
    document_type: string; document_type_label: string;
    compliance_status: string; summary: string; analyzed: boolean;
  },
  analyze: vi.fn(),
  chatSend: vi.fn(),
}));

vi.mock("./hooks/useAuth", () => ({ useAuth: () => ({
  user: state.user, loading: false, login: vi.fn(), logout: vi.fn(),
}) }));
vi.mock("./hooks/useDocuments", () => ({ useDocuments: () => ({
  documents: state.selectedDocument ? [state.selectedDocument] : [],
  selectedDocument: state.selectedDocument, analysis: null, loading: false,
  uploading: false, analyzing: false, analyzingStoragePath: null,
  updatingFields: false, deleting: false, error: null,
  setSelectedDocument: vi.fn(), upload: vi.fn(), analyze: state.analyze,
  updateFields: vi.fn(), deleteDocument: vi.fn(),
}) }));
vi.mock("./hooks/useChatWorkflow", () => ({ useChatWorkflow: () => ({
  sessions: [], sessionsLoading: false, sessionsRefreshing: false, sessionsError: null,
  historyLoading: false, historyError: null,
  messages: [], loading: false, streamingText: "", pendingInterrupt: null,
  nodeStatus: {}, nodeResults: {}, nodeMeta: {}, planSteps: [],
  nodeLabels: {}, nodeOrder: [], planIntent: "", logs: [],
  toolCalls: [], guardrailEvents: [], send: state.chatSend, resume: vi.fn(), newChat: vi.fn(),
  cancel: vi.fn(), addUploadMessage: vi.fn(), retrySessions: vi.fn(), retryHistory: vi.fn(),
}) }));
vi.mock("./layouts/AppShell", () => ({ AppShell: ({ children }: { children: ReactNode }) => <div>{children}</div> }));
vi.mock("./features/documents/DocumentLibraryPanel", () => ({ DocumentLibraryPanel: () => null }));
vi.mock("./features/chat/DecisionFlow", () => ({ DecisionFlow: () => null }));
vi.mock("./pages/LoginPage", () => ({ LoginPage: () => <h1>Login screen</h1> }));
vi.mock("./pages/HomePage", () => ({ HomePage: () => <h1>Home screen</h1> }));
vi.mock("./pages/DraftsPage", () => ({ DraftsPage: () => <h1>Drafts screen</h1> }));
vi.mock("./pages/ChatsPage", () => ({ ChatsPage: ({ onSend }: { onSend: (text: string, level: "balanced", useDocument: boolean) => Promise<void> }) => <><h1>Chats screen</h1><button onClick={() => void onSend("Analiz et", "balanced", true)}>Send pending document</button></> }));
vi.mock("./pages/AdminPage", () => ({ AdminPage: () => <h1>Admin screen</h1> }));

function LocationProbe() {
  return <output>{useLocation().pathname}</output>;
}

describe("application route guards", () => {
  beforeEach(() => {
    state.selectedDocument = null;
    state.analyze.mockReset();
    state.chatSend.mockReset();
  });
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

    await waitFor(() => expect(screen.getByText("/home")).toBeInTheDocument());
    expect(screen.queryByText("Admin screen")).not.toBeInTheDocument();
  });

  it("uses the dashboard as the authenticated entry point", async () => {
    state.user = {
      id: "employee-1", username: "employee", email: "employee@example.test",
      role: "employee", clearance_level: "hizmete_ozel", is_active: true, is_deleted: false,
    };
    render(<MemoryRouter initialEntries={["/"]}><App /><LocationProbe /></MemoryRouter>);

    expect(await screen.findByText("Home screen")).toBeInTheDocument();
    expect(screen.getByText("/home")).toBeInTheDocument();
  });

  it("keeps old routing links working by opening drafts", async () => {
    state.user = {
      id: "employee-1", username: "employee", email: "employee@example.test",
      role: "employee", clearance_level: "hizmete_ozel", is_active: true, is_deleted: false,
    };
    render(<MemoryRouter initialEntries={["/routing"]}><App /><LocationProbe /></MemoryRouter>);

    expect(await screen.findByText("Drafts screen")).toBeInTheDocument();
    expect(screen.getByText("/drafts")).toBeInTheDocument();
  });

  it("analyzes a pending document before sending it to chat", async () => {
    state.user = {
      id: "employee-1", username: "employee", email: "employee@example.test",
      role: "employee", clearance_level: "hizmete_ozel", is_active: true, is_deleted: false,
    };
    state.selectedDocument = {
      file_name: "bekleyen.pdf",
      storage_path: "pending:document",
      upload_time: "2026-08-12T10:00:00Z",
      document_type: "",
      document_type_label: "",
      compliance_status: "",
      summary: "",
      analyzed: false,
    };
    state.analyze.mockResolvedValue({ storage_path: "uploads/analyzed.pdf" });

    render(<MemoryRouter initialEntries={["/chats"]}><App /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Send pending document" }));

    await waitFor(() => expect(state.analyze).toHaveBeenCalledWith("pending:document"));
    expect(state.chatSend).toHaveBeenCalledWith(
      "Analiz et",
      "balanced",
      true,
      "uploads/analyzed.pdf",
      undefined,
    );
  });
});
