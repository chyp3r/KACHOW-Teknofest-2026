import type { ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const state = vi.hoisted(() => ({
  user: null as null | {
    id: string; username: string; email: string; role: "employee" | "manager" | "admin";
    clearance_level: "hizmete_ozel"; is_active: boolean; is_deleted: boolean;
  },
  selectedDocument: null as null | {
    file_name: string; storage_path: string; upload_time: string;
    document_type: string; document_type_label: string;
    compliance_status: string; summary: string; analyzed: boolean;
  },
  upload: vi.fn(),
  analyze: vi.fn(),
  chatSend: vi.fn(),
  chatNew: vi.fn(),
  chatCancel: vi.fn(),
  resolveChatSession: null as null | ((sessionId: string) => void),
  activeChatSessionId: null as string | null,
}));

vi.mock("./hooks/useAuth", () => ({ useAuth: () => ({
  user: state.user, loading: false, login: vi.fn(), logout: vi.fn(),
}) }));
vi.mock("./hooks/useDocuments", () => ({ useDocuments: () => ({
  documents: state.selectedDocument ? [state.selectedDocument] : [],
  selectedDocument: state.selectedDocument, analysis: null, loading: false,
  uploading: false, analyzing: false, analyzingStoragePath: null,
  updatingFields: false, deleting: false, error: null,
  setSelectedDocument: vi.fn(), upload: state.upload, analyze: state.analyze,
  updateFields: vi.fn(), deleteDocument: vi.fn(),
}) }));
vi.mock("./hooks/useChatWorkflow", () => ({ useChatWorkflow: (
  _document: unknown,
  _userId: string,
  activeSessionId: string | null,
  onSessionResolved?: (sessionId: string) => void,
) => {
  state.activeChatSessionId = activeSessionId;
  state.resolveChatSession = onSessionResolved ?? null;
  return ({
  sessions: [], sessionsLoading: false, sessionsRefreshing: false, sessionsError: null,
  historyLoading: false, historyError: null,
  messages: [], loading: false, streamingText: "", pendingInterrupt: null,
  nodeStatus: {}, nodeResults: {}, nodeMeta: {}, planSteps: [],
  nodeLabels: {}, nodeOrder: [], planIntent: "", logs: [],
  toolCalls: [], guardrailEvents: [], send: state.chatSend, resume: vi.fn(), newChat: state.chatNew,
  cancel: state.chatCancel, addUploadMessage: vi.fn(), retrySessions: vi.fn(), retryHistory: vi.fn(),
  });
} }));
vi.mock("./layouts/AppShell", () => ({ AppShell: ({ children }: { children: ReactNode }) => <div>{children}</div> }));
vi.mock("./features/documents/DocumentLibraryPanel", () => ({ DocumentLibraryPanel: () => null }));
vi.mock("./features/chat/DecisionFlow", () => ({ DecisionFlow: () => null }));
vi.mock("./pages/LoginPage", () => ({ LoginPage: () => <h1>Login screen</h1> }));
vi.mock("./pages/HomePage", () => ({ HomePage: () => <h1>Home screen</h1> }));
vi.mock("./pages/DraftsPage", () => ({ DraftsPage: () => <h1>Drafts screen</h1> }));
vi.mock("./pages/ChatsPage", () => ({ ChatsPage: ({ onSend, onNewChat }: { onSend: (text: string, level: "balanced", useDocument: boolean) => Promise<void>; onNewChat: () => void }) => <><h1>Chats screen</h1><button onClick={() => void onSend("Analiz et", "balanced", true)}>Send pending document</button><button onClick={onNewChat}>New chat</button></> }));
vi.mock("./pages/DocumentsPage", () => ({ DocumentsPage: ({ onCloseDocument, onUpload }: { onCloseDocument?: () => void; onUpload: (file: File) => Promise<void> }) => <><h1>Documents screen</h1><button onClick={() => void onUpload(new File(["belge"], "yeni.pdf", { type: "application/pdf" }))}>Upload document</button>{onCloseDocument && <button onClick={onCloseDocument}>Liste görünümüne dön</button>}</> }));
vi.mock("./pages/AdminPage", () => ({ AdminPage: () => <h1>Admin screen</h1> }));
vi.mock("./pages/StatusPage", () => ({ StatusPage: () => <h1>Status screen</h1> }));

function LocationProbe() {
  return <output>{useLocation().pathname}</output>;
}

function RouteControls() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate("/home")}>Go home</button><button onClick={() => navigate("/chats")}>Go chats</button></>;
}

describe("application route guards", () => {
  beforeEach(() => {
    state.selectedDocument = null;
    state.upload.mockReset();
    state.analyze.mockReset();
    state.chatSend.mockReset();
    state.chatNew.mockReset();
    state.chatCancel.mockReset();
    state.resolveChatSession = null;
    state.activeChatSessionId = null;
    sessionStorage.clear();
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

  it("allows managers into management but redirects them away from system status", async () => {
    state.user = {
      id: "manager-1", username: "manager", email: "manager@example.test",
      role: "manager", clearance_level: "hizmete_ozel", is_active: true, is_deleted: false,
    };
    const management = render(
      <MemoryRouter initialEntries={["/admin"]}><App /><LocationProbe /></MemoryRouter>,
    );

    expect(await screen.findByText("Admin screen")).toBeInTheDocument();
    expect(screen.getByText("/admin")).toBeInTheDocument();
    management.unmount();

    render(<MemoryRouter initialEntries={["/status"]}><App /><LocationProbe /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("/home")).toBeInTheDocument());
    expect(screen.queryByText("Status screen")).not.toBeInTheDocument();
  });

  it("keeps system status available to admins", async () => {
    state.user = {
      id: "admin-1", username: "admin", email: "admin@example.test",
      role: "admin", clearance_level: "hizmete_ozel", is_active: true, is_deleted: false,
    };
    render(<MemoryRouter initialEntries={["/status"]}><App /><LocationProbe /></MemoryRouter>);

    expect(await screen.findByText("Status screen")).toBeInTheDocument();
    expect(screen.getByText("/status")).toBeInTheDocument();
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

  it("returns from a document detail route with one close action", async () => {
    state.user = {
      id: "employee-1", username: "employee", email: "employee@example.test",
      role: "employee", clearance_level: "hizmete_ozel", is_active: true, is_deleted: false,
    };
    state.selectedDocument = {
      file_name: "izin.pdf",
      storage_path: "documents/izin.pdf",
      upload_time: "2026-08-12T10:00:00Z",
      document_type: "petition",
      document_type_label: "Dilekçe",
      compliance_status: "compliant",
      summary: "İzin talebi",
      analyzed: true,
    };

    render(<MemoryRouter initialEntries={["/documents/documents%2Fizin.pdf"]}><App /><LocationProbe /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: "Liste görünümüne dön" }));
    await waitFor(() => expect(screen.getByText("/documents")).toBeInTheDocument());
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

  it("opens a staged document route immediately after upload", async () => {
    state.user = {
      id: "employee-1", username: "employee", email: "employee@example.test",
      role: "employee", clearance_level: "hizmete_ozel", is_active: true, is_deleted: false,
    };
    state.upload.mockResolvedValue({
      file_name: "yeni.pdf",
      storage_path: "pending:document",
      upload_time: "2026-08-24T16:49:00Z",
      document_type: "",
      document_type_label: "",
      compliance_status: "",
      summary: "",
      analyzed: false,
    });

    render(<MemoryRouter initialEntries={["/documents"]}><App /><LocationProbe /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Upload document" }));

    await waitFor(() => expect(state.upload).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getByText("/documents/pending%3Adocument")).toBeInTheDocument(),
    );
  });

  it("restores the last chat after leaving the page until a new chat is requested", async () => {
    state.user = {
      id: "employee-1", username: "employee", email: "employee@example.test",
      role: "employee", clearance_level: "hizmete_ozel", is_active: true, is_deleted: false,
    };

    render(<MemoryRouter initialEntries={["/chats/employee-1:web:last"]}><App /><RouteControls /><LocationProbe /></MemoryRouter>);

    await waitFor(() => expect(state.activeChatSessionId).toBe("employee-1:web:last"));
    expect(sessionStorage.getItem("kachow.chat.last-session.employee-1")).toBe("employee-1:web:last");

    fireEvent.click(screen.getByRole("button", { name: "Go home" }));
    await waitFor(() => expect(screen.getByText("/home")).toBeInTheDocument());
    expect(state.activeChatSessionId).toBe("employee-1:web:last");

    fireEvent.click(screen.getByRole("button", { name: "Go chats" }));
    await waitFor(() => expect(screen.getByText("/chats/employee-1%3Aweb%3Alast")).toBeInTheDocument());
    expect(state.activeChatSessionId).toBe("employee-1:web:last");

    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    await waitFor(() => expect(screen.getByText("/chats")).toBeInTheDocument());
    expect(state.activeChatSessionId).toBeNull();
    expect(sessionStorage.getItem("kachow.chat.last-session.employee-1")).toBeNull();
    expect(state.chatNew).toHaveBeenCalledOnce();
  });

  it("keeps chat processing when navigating away and does not pull the user back", async () => {
    state.user = {
      id: "employee-1", username: "employee", email: "employee@example.test",
      role: "employee", clearance_level: "hizmete_ozel", is_active: true, is_deleted: false,
    };

    render(
      <MemoryRouter initialEntries={["/chats"]}>
        <App />
        <RouteControls />
        <LocationProbe />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Chats screen")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Go home" }));
    await waitFor(() => expect(screen.getByText("/home")).toBeInTheDocument());

    expect(state.chatCancel).not.toHaveBeenCalled();
    act(() => state.resolveChatSession?.("employee-1:web:background"));

    await waitFor(() =>
      expect(sessionStorage.getItem("kachow.chat.last-session.employee-1"))
        .toBe("employee-1:web:background"),
    );
    expect(screen.getByText("/home")).toBeInTheDocument();
    expect(state.chatCancel).not.toHaveBeenCalled();
  });
});
