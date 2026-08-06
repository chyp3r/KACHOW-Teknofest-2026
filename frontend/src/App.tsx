import { useEffect, useState } from "react";
import { DecisionFlow } from "./features/chat/DecisionFlow";
import { DocumentLibraryPanel } from "./features/documents/DocumentLibraryPanel";
import { useAppRoute, type AppRoute } from "./hooks/useAppRoute";
import { useAuth } from "./hooks/useAuth";
import { useChatWorkflow } from "./hooks/useChatWorkflow";
import {
  useDraftHistory,
  type DraftHistoryEntry,
} from "./hooks/useDraftHistory";
import { useDocuments } from "./hooks/useDocuments";
import { AppShell } from "./layouts/AppShell";
import { AdminPage } from "./pages/AdminPage";
import { ChatsPage } from "./pages/ChatsPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { DraftsPage } from "./pages/DraftsPage";
import { LoginPage } from "./pages/LoginPage";
import type { DocumentMetadata, DraftResult } from "./types/documents";

function AuthenticatedApp({
  route,
  navigate,
  userId,
}: {
  route: AppRoute;
  navigate: (route: AppRoute) => void;
  userId: string;
}) {
  const documents = useDocuments(userId);
  const chat = useChatWorkflow(documents.selectedDocument, userId);
  const draftHistory = useDraftHistory(userId);
  const [draft, setDraft] = useState<DraftResult | null>(null);
  const [workflowOpen, setWorkflowOpen] = useState(false);
  const [documentLibraryOpen, setDocumentLibraryOpen] = useState(false);

  const selectDocument = (document: DocumentMetadata) => {
    documents.setSelectedDocument(document);
    setDraft(null);
  };

  const uploadDocument = async (file: File) => {
    await documents.upload(file);
    setDraft(null);
    chat.addUploadMessage(file.name);
  };

  const recordDraft = (createdDraft: DraftResult) => {
    setDraft(createdDraft);
    if (documents.selectedDocument) {
      draftHistory.addDraft(createdDraft, documents.selectedDocument);
    }
  };

  const openDraftHistory = (entry: DraftHistoryEntry) => {
    documents.setSelectedDocument(entry.source);
    setDraft(entry.result);
  };

  const page = (() => {
    switch (route) {
      case "/documents":
        return (
          <DocumentsPage
            documents={documents.documents}
            selected={documents.selectedDocument}
            analysis={documents.analysis}
            loading={documents.loading}
            uploading={documents.uploading}
            error={documents.error}
            onUpload={uploadDocument}
            onSelect={selectDocument}
          />
        );
      case "/drafts":
        return (
          <DraftsPage
            documents={documents.documents}
            selected={documents.selectedDocument}
            analysis={documents.analysis}
            draft={draft}
            history={draftHistory.entries}
            onSelect={selectDocument}
            onDraftCreated={recordDraft}
            onHistorySelect={openDraftHistory}
          />
        );
      case "/admin":
        return <AdminPage onLogin={() => navigate("/login")} />;
      case "/chats":
      default:
        return (
          <ChatsPage
            documents={documents.documents}
            selectedDocument={documents.selectedDocument}
            messages={chat.messages}
            streamingText={chat.streamingText}
            loading={chat.loading}
            logs={chat.logs}
            guardrailEvents={chat.guardrailEvents}
            interrupt={chat.pendingInterrupt}
            workflowOpen={workflowOpen}
            onSelectDocument={selectDocument}
            onClearDocument={() => documents.setSelectedDocument(null)}
            onSend={chat.send}
            onResume={chat.resume}
            onNewChat={chat.newChat}
            onToggleWorkflow={() => setWorkflowOpen((open) => !open)}
          />
        );
    }
  })();

  return (
    <AppShell
      route={route}
      navigate={navigate}
      documentLibraryOpen={documentLibraryOpen}
      onToggleDocumentLibrary={() =>
        setDocumentLibraryOpen((open) => !open)
      }
      documentLibrary={
        <DocumentLibraryPanel
          documents={documents.documents}
          selected={documents.selectedDocument}
          loading={documents.loading}
          uploading={documents.uploading}
          error={documents.error}
          onUpload={uploadDocument}
          onSelect={selectDocument}
          onViewDetails={() => {
            setDocumentLibraryOpen(false);
            navigate("/documents");
          }}
        />
      }
      aside={
        route === "/chats" && workflowOpen ? (
          <DecisionFlow
            statuses={chat.nodeStatus}
            results={chat.nodeResults}
            meta={chat.nodeMeta}
            planSteps={chat.planSteps}
            toolCalls={chat.toolCalls}
            guardrailEvents={chat.guardrailEvents}
            onClose={() => setWorkflowOpen(false)}
          />
        ) : undefined
      }
    >
      {page}
    </AppShell>
  );
}

export default function App() {
  const { user, loading } = useAuth();
  const { route, navigate } = useAppRoute();

  useEffect(() => {
    if (loading) return;
    if (!user && route !== "/login") navigate("/login");
    if (user && route === "/login") navigate("/chats");
  }, [loading, navigate, route, user]);

  if (loading) {
    return <div className="centered-state app-loading">Oturum doğrulanıyor…</div>;
  }
  if (!user) {
    return <LoginPage onSuccess={() => navigate("/chats")} />;
  }
  return <AuthenticatedApp route={route} navigate={navigate} userId={user.id} />;
}
