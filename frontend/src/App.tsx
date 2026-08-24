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
const HomePage = lazy(() => import("./pages/HomePage").then((module) => ({ default: module.HomePage })));
const ChatsPage = lazy(() => import("./pages/ChatsPage").then((module) => ({ default: module.ChatsPage })));
const DocumentsPage = lazy(() => import("./pages/DocumentsPage").then((module) => ({ default: module.DocumentsPage })));
const DraftsPage = lazy(() => import("./pages/DraftsPage").then((module) => ({ default: module.DraftsPage })));
const GraphPage = lazy(() => import("./pages/GraphPage").then((module) => ({ default: module.GraphPage })));
const MessagesPage = lazy(() => import("./pages/MessagesPage").then((module) => ({ default: module.MessagesPage })));
const AdminPage = lazy(() => import("./pages/AdminPage").then((module) => ({ default: module.AdminPage })));
const AccountPage = lazy(() => import("./pages/AccountPage").then((module) => ({ default: module.AccountPage })));
const StatusPage = lazy(() => import("./pages/StatusPage").then((module) => ({ default: module.StatusPage })));
const PlatformPage = lazy(() => import("./pages/PlatformPage").then((module) => ({ default: module.PlatformPage })));
const NotFoundPage = lazy(() => import("./pages/NotFoundPage").then((module) => ({ default: module.NotFoundPage })));

const PageFallback = () => <div className="centered-state app-loading">Sayfa yükleniyor…</div>;

function RootAuthenticatedApp() {
  return <AppShell><Suspense fallback={<PageFallback />}><Routes><Route path="/platform" element={<PlatformPage />} /><Route path="/account" element={<AccountPage />} /><Route path="*" element={<Navigate to="/platform" replace />} /></Routes></Suspense></AppShell>;
}

function AuthenticatedApp({ userId }: { userId: string }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const chatMatch = useMatch("/chats/:sessionId");
  const draftMatch = useMatch("/drafts/:draftId");
  const documentMatch = useMatch("/documents/:storagePath");
  const messagesMatch = useMatch("/messages/:conversationId");
  const routeSessionId = chatMatch?.params.sessionId ?? null;
  const [retainedSessionId, setRetainedSessionId] = useState<string | null>(routeSessionId);
  const activeDraftId = draftMatch?.params.draftId;
  const activeConversationId = messagesMatch?.params.conversationId;
  const documents = useDocuments(userId);
  const documentItems = documents.documents;
  const selectedDocument = documents.selectedDocument;
  const setSelectedDocument = documents.setSelectedDocument;
  const [workflowOpen, setWorkflowOpen] = useState(false);
  const [chatHistoryOpen, setChatHistoryOpen] = useState(false);
  useEffect(() => {
    if (routeSessionId) setRetainedSessionId(routeSessionId);
  }, [routeSessionId]);
  const onSessionResolved = useCallback((sessionId: string) => {
    setRetainedSessionId(sessionId);
    navigate(`/chats/${encodeURIComponent(sessionId)}`, { replace: true });
  }, [navigate]);
  const chat = useChatWorkflow(documents.selectedDocument, userId, retainedSessionId, onSessionResolved);

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
      setChatHistoryOpen(false);
      setWorkflowOpen(false);
    }
  }, [location.pathname]);

  const selectDocument = (document: DocumentMetadata) => {
    documents.setSelectedDocument(document);
  };
  const uploadDocument = async (file: File) => {
    await documents.upload(file);
  };
  const uploadDocumentToChat = async (file: File) => {
    const uploaded = await documents.upload(file);
    await documents.analyze(uploaded.storage_path);
    chat.addUploadMessage(file.name);
  };
  const analyzeDocument = async (storagePath: string) => {
    const analysis = await documents.analyze(storagePath);
    if (documentMatch?.params.storagePath === storagePath) {
      navigate(`/documents/${encodeURIComponent(analysis.storage_path)}`, { replace: true });
    }
    return analysis;
  };
  const sendChatMessage = async (text: string, level: Parameters<typeof chat.send>[1], useDocument: boolean, draftId?: string | null) => {
    let analyzedStoragePath: string | undefined;
    if (useDocument && documents.selectedDocument?.analyzed === false) {
      try {
        const analysis = await documents.analyze(documents.selectedDocument.storage_path);
        analyzedStoragePath = analysis.storage_path;
      } catch {
        return;
      }
    }
    await chat.send(text, level, useDocument, analyzedStoragePath, draftId);
  };
  const canManage = user?.role === "admin" || user?.role === "manager";
  const chatsPage = (
    <ChatsPage
      documents={documents.documents}
      sessions={chat.sessions}
      activeSessionId={retainedSessionId}
      sessionsLoading={chat.sessionsLoading}
      sessionsRefreshing={chat.sessionsRefreshing}
      sessionsError={chat.sessionsError}
      historyLoading={chat.historyLoading}
      historyError={chat.historyError}
      documentError={documents.error}
      selectedDocument={documents.selectedDocument}
      messages={chat.messages}
      streamingText={chat.streamingText}
      loading={chat.loading}
      guardrailEvents={chat.guardrailEvents}
      interrupt={chat.pendingInterrupt}
      workflowOpen={workflowOpen}
      historyOpen={chatHistoryOpen}
      planSteps={chat.planSteps}
      nodeOrder={chat.nodeOrder}
      nodeLabels={chat.nodeLabels}
      nodeStatus={chat.nodeStatus}
      nodeMeta={chat.nodeMeta}
      nodeResults={chat.nodeResults}
      toolCalls={chat.toolCalls}
      nodeStartedAt={chat.nodeStartedAt}
      turnStartedAt={chat.turnStartedAt}
      onSelectDocument={selectDocument}
      onClearDocument={() => documents.setSelectedDocument(null)}
      onSend={sendChatMessage}
      onResume={chat.resume}
      onNewChat={() => { setChatHistoryOpen(false); setRetainedSessionId(null); chat.newChat(); navigate("/chats"); }}
      onOpenSession={(sessionId) => {
        setChatHistoryOpen(false);
        setRetainedSessionId(sessionId);
        navigate(`/chats/${encodeURIComponent(sessionId)}`);
      }}
      onCloseHistory={() => setChatHistoryOpen(false)}
      onOpenHistory={() => setChatHistoryOpen(true)}
      onRetrySessions={chat.retrySessions}
      onRetryHistory={chat.retryHistory}
      onCancel={chat.cancel}
      onToggleWorkflow={() => setWorkflowOpen((open) => !open)}
      onUploadDocument={uploadDocumentToChat}
      documentUploading={documents.analyzing}
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
          <Route path="/" element={<Navigate to="/home" replace />} />
          <Route path="/home" element={<HomePage documents={documents.documents} loading={documents.loading} />} />
          <Route path="/chats" element={chatsPage} />
          <Route path="/chats/:sessionId" element={chatsPage} />
          <Route path="/documents" element={<DocumentsPage canPush={canManage} documents={documents.documents} selected={documents.selectedDocument} analysis={documents.analysis} loading={documents.loading} uploading={documents.uploading} updatingFields={documents.updatingFields} analyzingStoragePath={documents.analyzingStoragePath} deletingDocument={documents.deleting} error={documents.error} onUpload={uploadDocument} onUpdateFields={documents.updateFields} onAnalyzeDocument={analyzeDocument} onDeleteDocument={documents.deleteDocument} onGenerateDetailedSummary={documents.generateDetailedSummary} generatingDetailedSummary={documents.generatingDetailedSummary} documentText={documents.documentText} onSaveText={documents.saveText} savingText={documents.savingText} onReextract={documents.reextractText} reextracting={documents.reextracting} onSelect={(document) => { selectDocument(document); navigate(`/documents/${encodeURIComponent(document.storage_path)}`); }} onCloseDocument={() => { documents.setSelectedDocument(null); navigate("/documents"); }} />} />
          <Route path="/documents/:storagePath" element={<DocumentsPage canPush={canManage} documents={documents.documents} selected={documents.selectedDocument} analysis={documents.analysis} loading={documents.loading} uploading={documents.uploading} updatingFields={documents.updatingFields} analyzingStoragePath={documents.analyzingStoragePath} deletingDocument={documents.deleting} error={documents.error} onUpload={uploadDocument} onUpdateFields={documents.updateFields} onAnalyzeDocument={analyzeDocument} onDeleteDocument={documents.deleteDocument} onGenerateDetailedSummary={documents.generateDetailedSummary} generatingDetailedSummary={documents.generatingDetailedSummary} documentText={documents.documentText} onSaveText={documents.saveText} savingText={documents.savingText} onReextract={documents.reextractText} reextracting={documents.reextracting} onSelect={(document) => { selectDocument(document); navigate(`/documents/${encodeURIComponent(document.storage_path)}`); }} onCloseDocument={() => { documents.setSelectedDocument(null); navigate("/documents"); }} />} />
          <Route path="/drafts" element={<DraftsPage documents={documents.documents} selected={documents.selectedDocument} analysis={documents.analysis} onSelect={selectDocument} onOpenDraft={(draftId) => navigate(`/drafts/${encodeURIComponent(draftId)}`)} onCloseDraft={() => navigate("/drafts")} />} />
          <Route path="/drafts/:draftId" element={<DraftsPage documents={documents.documents} selected={documents.selectedDocument} analysis={documents.analysis} activeDraftId={activeDraftId} onSelect={selectDocument} onOpenDraft={(draftId) => navigate(`/drafts/${encodeURIComponent(draftId)}`)} onCloseDraft={() => navigate("/drafts")} />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/messages" element={<MessagesPage currentUserId={userId} onSelectConversation={(conversationId) => navigate(`/messages/${encodeURIComponent(conversationId)}`)} onCloseConversation={() => navigate("/messages")} />} />
          <Route path="/messages/:conversationId" element={<MessagesPage currentUserId={userId} activeConversationId={activeConversationId} onSelectConversation={(conversationId) => navigate(`/messages/${encodeURIComponent(conversationId)}`)} onCloseConversation={() => navigate("/messages")} />} />
          <Route path="/routing" element={<Navigate to="/drafts" replace />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/admin" element={canManage ? <AdminPage onLogin={() => navigate("/login")} /> : <Navigate to="/home" replace />} />
          <Route path="/status" element={canManage ? <StatusPage /> : <Navigate to="/home" replace />} />
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
        <Route path="/login" element={user ? <Navigate to={user.role === "root" ? "/platform" : "/home"} replace /> : <LoginPage onSuccess={() => undefined} />} />
        <Route path="/*" element={user ? (user.role === "root" ? <RootAuthenticatedApp /> : <AuthenticatedApp userId={user.id} />) : <Navigate to="/login" replace state={{ from: location.pathname }} />} />
      </Routes>
    </Suspense>
  );
}
