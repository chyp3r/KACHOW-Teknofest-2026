import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation, useMatch, useNavigate } from "react-router-dom";
import { DecisionFlow } from "./features/chat/DecisionFlow";
import { useAuth } from "./hooks/useAuth";
import { useChatWorkflow } from "./hooks/useChatWorkflow";
import { useDocuments } from "./hooks/useDocuments";
import { AppShell } from "./layouts/AppShell";
import type { DocumentMetadata } from "./types/documents";
import { OverlayBackdrop } from "./components/Surface";

const LoginPage = lazy(() => import("./pages/LoginPage").then((module) => ({ default: module.LoginPage })));
const ChatsPage = lazy(() => import("./pages/ChatsPage").then((module) => ({ default: module.ChatsPage })));
const DocumentsPage = lazy(() => import("./pages/DocumentsPage").then((module) => ({ default: module.DocumentsPage })));
const DraftsPage = lazy(() => import("./pages/DraftsPage").then((module) => ({ default: module.DraftsPage })));
const RoutingPage = lazy(() => import("./pages/RoutingPage").then((module) => ({ default: module.RoutingPage })));
const AdminPage = lazy(() => import("./pages/AdminPage").then((module) => ({ default: module.AdminPage })));
const AccountPage = lazy(() => import("./pages/AccountPage").then((module) => ({ default: module.AccountPage })));
const StatusPage = lazy(() => import("./pages/StatusPage").then((module) => ({ default: module.StatusPage })));
const NotFoundPage = lazy(() => import("./pages/NotFoundPage").then((module) => ({ default: module.NotFoundPage })));

const PageFallback = () => <div className="centered-state app-loading">Sayfa yükleniyor…</div>;

function AuthenticatedApp({ userId }: { userId: string }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const chatMatch = useMatch("/chats/:sessionId");
  const draftMatch = useMatch("/drafts/:draftId");
  const documentMatch = useMatch("/documents/:storagePath");
  const activeSessionId = chatMatch?.params.sessionId ?? null;
  const activeDraftId = draftMatch?.params.draftId;
  const documents = useDocuments(userId);
  const documentItems = documents.documents;
  const selectedDocument = documents.selectedDocument;
  const setSelectedDocument = documents.setSelectedDocument;
  const [workflowOpen, setWorkflowOpen] = useState(false);
  const [chatHistoryOpen, setChatHistoryOpen] = useState(false);
  const onSessionResolved = useCallback((sessionId: string) => {
    navigate(`/chats/${encodeURIComponent(sessionId)}`, { replace: true });
  }, [navigate]);
  const chat = useChatWorkflow(documents.selectedDocument, userId, activeSessionId, onSessionResolved);
  const cancelChat = chat.cancel;

  useEffect(() => {
    const storagePath = documentMatch?.params.storagePath;
    if (!storagePath || documentItems.length === 0) return;
    const match = documentItems.find((item) => item.storage_path === storagePath);
    if (match && match.storage_path !== selectedDocument?.storage_path) {
      setSelectedDocument(match);
    }
  }, [documentItems, documentMatch?.params.storagePath, selectedDocument?.storage_path, setSelectedDocument]);

  useEffect(() => {
    if (!location.pathname.startsWith("/chats")) {
      cancelChat();
      setChatHistoryOpen(false);
      setWorkflowOpen(false);
    }
  }, [cancelChat, location.pathname]);

  const selectDocument = (document: DocumentMetadata) => {
    documents.setSelectedDocument(document);
  };
  const uploadDocument = async (file: File) => {
    await documents.upload(file);
    chat.addUploadMessage(file.name);
  };
  const canManage = user?.role === "admin" || user?.role === "manager";
  const chatsPage = (
    <ChatsPage
      documents={documents.documents}
      sessions={chat.sessions}
      activeSessionId={activeSessionId}
      sessionsLoading={chat.sessionsLoading}
      sessionsRefreshing={chat.sessionsRefreshing}
      sessionsError={chat.sessionsError}
      historyLoading={chat.historyLoading}
      historyError={chat.historyError}
      selectedDocument={documents.selectedDocument}
      messages={chat.messages}
      streamingText={chat.streamingText}
      loading={chat.loading}
      logs={chat.logs}
      guardrailEvents={chat.guardrailEvents}
      interrupt={chat.pendingInterrupt}
      workflowOpen={workflowOpen}
      historyOpen={chatHistoryOpen}
      onSelectDocument={selectDocument}
      onClearDocument={() => documents.setSelectedDocument(null)}
      onSend={chat.send}
      onResume={chat.resume}
      onNewChat={() => { setChatHistoryOpen(false); chat.newChat(); navigate("/chats"); }}
      onOpenSession={(sessionId) => {
        setChatHistoryOpen(false);
        navigate(`/chats/${encodeURIComponent(sessionId)}`);
      }}
      onCloseHistory={() => setChatHistoryOpen(false)}
      onOpenHistory={() => setChatHistoryOpen(true)}
      onRetrySessions={chat.retrySessions}
      onRetryHistory={chat.retryHistory}
      onCancel={chat.cancel}
      onToggleWorkflow={() => setWorkflowOpen((open) => !open)}
      onUploadDocument={uploadDocument}
      documentUploading={documents.uploading}
    />
  );

  return (
    <AppShell
      aside={
        location.pathname.startsWith("/chats") && workflowOpen ? (
          <>
            <OverlayBackdrop
              className="workflow-backdrop"
              aria-label="İş akışını kapat"
              onClick={() => setWorkflowOpen(false)}
            />
            <DecisionFlow
              statuses={chat.nodeStatus}
              results={chat.nodeResults}
              meta={chat.nodeMeta}
              planSteps={chat.planSteps}
              nodeLabels={chat.nodeLabels}
              nodeOrder={chat.nodeOrder}
              planIntent={chat.planIntent}
              toolCalls={chat.toolCalls}
              guardrailEvents={chat.guardrailEvents}
              onClose={() => setWorkflowOpen(false)}
            />
          </>
        ) : undefined
      }
    >
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/chats" element={chatsPage} />
          <Route path="/chats/:sessionId" element={chatsPage} />
          <Route path="/documents" element={<DocumentsPage documents={documents.documents} selected={documents.selectedDocument} analysis={documents.analysis} loading={documents.loading} uploading={documents.uploading} updatingFields={documents.updatingFields} deletingDocument={documents.deleting} error={documents.error} onUpload={uploadDocument} onUpdateFields={documents.updateFields} onDeleteDocument={documents.deleteDocument} onSelect={(document) => { selectDocument(document); navigate(`/documents/${encodeURIComponent(document.storage_path)}`); }} onCloseDocument={() => { documents.setSelectedDocument(null); navigate("/documents"); }} />} />
          <Route path="/documents/:storagePath" element={<DocumentsPage documents={documents.documents} selected={documents.selectedDocument} analysis={documents.analysis} loading={documents.loading} uploading={documents.uploading} updatingFields={documents.updatingFields} deletingDocument={documents.deleting} error={documents.error} onUpload={uploadDocument} onUpdateFields={documents.updateFields} onDeleteDocument={documents.deleteDocument} onSelect={(document) => { selectDocument(document); navigate(`/documents/${encodeURIComponent(document.storage_path)}`); }} onCloseDocument={() => { documents.setSelectedDocument(null); navigate("/documents"); }} />} />
          <Route path="/drafts" element={<DraftsPage documents={documents.documents} selected={documents.selectedDocument} analysis={documents.analysis} onSelect={selectDocument} onOpenDraft={(draftId) => navigate(`/drafts/${encodeURIComponent(draftId)}`)} onCloseDraft={() => navigate("/drafts")} />} />
          <Route path="/drafts/:draftId" element={<DraftsPage documents={documents.documents} selected={documents.selectedDocument} analysis={documents.analysis} activeDraftId={activeDraftId} onSelect={selectDocument} onOpenDraft={(draftId) => navigate(`/drafts/${encodeURIComponent(draftId)}`)} onCloseDraft={() => navigate("/drafts")} />} />
          <Route path="/routing" element={<RoutingPage />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/admin" element={canManage ? <AdminPage onLogin={() => navigate("/login")} /> : <Navigate to="/chats" replace />} />
          <Route path="/status" element={canManage ? <StatusPage /> : <Navigate to="/chats" replace />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}

export default function App() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="centered-state app-loading">Oturum doğrulanıyor…</div>;
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route path="/login" element={user ? <Navigate to="/chats" replace /> : <LoginPage onSuccess={() => undefined} />} />
        <Route path="/*" element={user ? <AuthenticatedApp userId={user.id} /> : <Navigate to="/login" replace state={{ from: location.pathname }} />} />
      </Routes>
    </Suspense>
  );
}
