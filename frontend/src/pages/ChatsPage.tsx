import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AlertCircle, GitBranch, History, PauseCircle, Plus, RotateCcw } from "lucide-react";
import { PageHeader } from "../components/PageHeader";
import { ChatComposer } from "../features/chat/ChatComposer";
import { ChatDropZone } from "../features/chat/ChatDropZone";
import { ConversationHistoryDrawer } from "../features/chat/ConversationHistoryDrawer";
import { guardrailDecisionLabel, formatGuardrailReason } from "../features/chat/guardrailLabels";
import { MessageList } from "../features/chat/MessageList";
import { SourcePeekDrawer, type CitationTarget } from "../features/chat/SourcePeekDrawer";
import type {
  ChatMessage,
  ChatSession,
  ContextUsage,
  GuardrailEvent,
  InterruptState,
  ToolCallEvent,
  WorkflowNodeStatus,
} from "../types/chat";
import type { DocumentMetadata, DocumentText, ReasoningLevel } from "../types/documents";
import { useDrafts } from "../hooks/useDrafts";
import { Button } from "../components/Button";
import { Alert, Spinner } from "../components/Surface";

export function ChatsPage({
  documents,
  sessions,
  activeSessionId,
  sessionsLoading,
  sessionsRefreshing,
  sessionsError,
  historyLoading,
  historyError,
  documentError,
  selectedDocument,
  documentText,
  messages,
  streamingText,
  loading,
  compacting,
  contextUsage,
  onCompact,
  guardrailEvents,
  interrupt,
  workflowOpen,
  historyOpen,
  planSteps = [],
  nodeOrder = [],
  nodeLabels = {},
  nodeStatus = {},
  nodeMeta = {},
  nodeResults = {},
  toolCalls = [],
  nodeStartedAt = {},
  turnStartedAt = null,
  onSelectDocument,
  onClearDocument,
  onSend,
  onResume,
  onNewChat,
  onOpenSession,
  onCloseHistory,
  onOpenHistory,
  onRetrySessions,
  onRetryHistory,
  onCancel,
  onToggleWorkflow,
  onUploadDocument,
  documentUploading = false,
}: {
  documents: DocumentMetadata[];
  sessions: ChatSession[];
  activeSessionId: string | null;
  sessionsLoading: boolean;
  sessionsRefreshing: boolean;
  sessionsError: string | null;
  historyLoading: boolean;
  historyError: string | null;
  documentError?: string | null;
  selectedDocument: DocumentMetadata | null;
  // Extracted page text for `selectedDocument`, already fetched by
  // useDocuments for whatever document is attached -- backs the source
  // view a page citation opens. Null while it loads or when nothing is
  // attached, in which case citations still render, just inertly.
  documentText?: DocumentText | null;
  messages: ChatMessage[];
  streamingText: string;
  loading: boolean;
  compacting: boolean;
  contextUsage: ContextUsage | null;
  onCompact: () => void | Promise<void>;
  guardrailEvents: GuardrailEvent[];
  interrupt: InterruptState | null;
  workflowOpen: boolean;
  historyOpen: boolean;
  // ThinkingBubble's live-progress data -- same shape useChatWorkflow
  // already exposes to DecisionFlow, threaded through here as well so the
  // waiting-state bubble in the chat flow shows the same "what's actually
  // happening" the workflow drawer does. Optional/defaulted so a caller
  // that only wants a plain loading state doesn't have to wire all of it.
  planSteps?: string[];
  nodeOrder?: string[];
  nodeLabels?: Record<string, string>;
  nodeStatus?: Record<string, WorkflowNodeStatus>;
  nodeMeta?: Record<string, Record<string, unknown>>;
  nodeResults?: Record<string, Record<string, unknown>>;
  toolCalls?: ToolCallEvent[];
  nodeStartedAt?: Record<string, number>;
  turnStartedAt?: number | null;
  onSelectDocument: (document: DocumentMetadata) => void;
  onClearDocument: () => void;
  onSend: (
    text: string,
    level: ReasoningLevel,
    useDocument: boolean,
    draftId?: string | null,
  ) => Promise<void>;
  onResume: (
    action: "answer" | "approve" | "revise" | "reject" | "select",
    answers: Record<string, string | string[]>,
    instructions: string,
  ) => Promise<void>;
  onNewChat: () => void;
  onOpenSession: (sessionId: string) => void;
  onCloseHistory: () => void;
  onOpenHistory: () => void;
  onRetrySessions: () => Promise<void>;
  onRetryHistory: () => Promise<void>;
  onCancel: () => void;
  onToggleWorkflow: () => void;
  onUploadDocument?: (file: File) => Promise<void>;
  documentUploading?: boolean;
}) {
  const [searchParams] = useSearchParams();
  const requestedDraftId = searchParams.get("draft");
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(requestedDraftId);
  const draftContext = useDrafts(selectedDraftId ?? undefined);
  const selectedDraft = draftContext.activeDraft
    ?? draftContext.drafts.find((draft) => draft.id === selectedDraftId)
    ?? null;
  const [promptTemplate, setPromptTemplate] = useState<string | null>(null);
  const historyTriggerRef = useRef<HTMLButtonElement>(null);
  // The page citation the reader clicked, if any -- see SourcePeekDrawer.
  const [citationTarget, setCitationTarget] = useState<CitationTarget | null>(null);

  useEffect(() => {
    if (requestedDraftId) setSelectedDraftId(requestedDraftId);
  }, [requestedDraftId]);

  const startNewChat = () => {
    setSelectedDraftId(null);
    onNewChat();
  };
  const openSession = (sessionId: string) => {
    setSelectedDraftId(null);
    onOpenSession(sessionId);
  };

  // ThinkingBubble's "taking longer than usual" shortcut -- cancels the
  // stalled turn and resends the same last user message at the "fast"
  // reasoning level. The setTimeout gives onCancel's abort() a tick to
  // reach send()'s catch/finally (aborting is asynchronous: the fetch
  // reader has to actually throw before `loading`/the in-flight request
  // ref clear), so an immediate re-send would otherwise be silently
  // dropped by send()'s own `if (loading || activeRequest.current) return`
  // guard.
  const retryFast = () => {
    const lastUserMessage = [...messages].reverse().find((message) => message.sender === "user");
    if (!lastUserMessage) return;
    onCancel();
    window.setTimeout(() => {
      void onSend(lastUserMessage.text, "fast", Boolean(selectedDocument), selectedDraft?.id);
    }, 50);
  };

  const page = (
    <div className="chat-page">
      <PageHeader
        title="Karar Destek Sohbeti"
        description="Evraklarınızı inceleyin, taslak hazırlayın ve işlem sürecini takip edin."
        secondaryActions={
          <>
            <Button
              ref={historyTriggerRef}
              variant="ghost"
              className="history-toggle"
              aria-haspopup="dialog"
              aria-expanded={historyOpen}
              aria-controls="conversation-history-drawer"
              onClick={onOpenHistory}
              leadingIcon={<History />}
            >
              Geçmiş
            </Button>
            <Button
              variant="secondary"
              className="workflow-toggle"
              aria-pressed={workflowOpen}
              onClick={onToggleWorkflow}
              leadingIcon={<GitBranch />}
            >
              {workflowOpen ? "İş akışını kapat" : "İş akışını göster"}
            </Button>
          </>
        }
        primaryAction={<Button leadingIcon={<Plus />} onClick={startNewChat}>Yeni sohbet</Button>}
      />
      {historyOpen && (
        <ConversationHistoryDrawer
          sessions={sessions}
          activeSessionId={activeSessionId}
          loading={sessionsLoading}
          refreshing={sessionsRefreshing}
          error={sessionsError}
          returnFocusRef={historyTriggerRef}
          onClose={onCloseHistory}
          onRetry={onRetrySessions}
          onNewChat={startNewChat}
          onOpenSession={openSession}
        />
      )}
      <SourcePeekDrawer
        target={citationTarget}
        pages={documentText?.pages ?? null}
        documentName={selectedDocument?.file_name}
        loading={Boolean(selectedDocument) && !documentText}
        onClose={() => setCitationTarget(null)}
      />
      <div className="chat-workspace">
        <div className="chat-content">
        {historyError && !historyOpen && (
          <Alert variant="error" icon={<AlertCircle />} action={<Button variant="ghost" size="sm" leadingIcon={<RotateCcw />} onClick={() => void onRetryHistory()}>Tekrar dene</Button>}>{historyError}</Alert>
        )}
        {documentError && (
          <Alert variant="error" icon={<AlertCircle />}>{documentError}</Alert>
        )}
        {draftContext.error && (
          <Alert variant="error" icon={<AlertCircle />}>{draftContext.error}</Alert>
        )}
        {historyLoading && <div className="processing-line"><Spinner label="Sohbet yükleniyor" />Sohbet yükleniyor…</div>}
        {guardrailEvents.length > 0 && (
          <div className="chat-guardrail-stack">
            {guardrailEvents.map((guardrail, index) => {
              const summary = guardrail.reasons.filter(
                (reason) => !reason.startsWith("Kaldırılan cümle:"),
              );
              const removed = guardrail.reasons
                .filter((reason) => reason.startsWith("Kaldırılan cümle:"))
                .map((reason) => reason.replace(/^Kaldırılan cümle:\s*/, ""));
              return (
                <Alert
                  variant={guardrail.decision === "blocked" ? "error" : "warning"}
                  title={`Güvenlik kontrolü: ${guardrailDecisionLabel(guardrail.decision)}`}
                  key={`${guardrail.stage}-${guardrail.kind}-${index}`}
                >
                  <div className="chat-guardrail-reasons">
                    {summary.length > 0 && (
                      <p>{summary.map(formatGuardrailReason).join(" · ")}</p>
                    )}
                    {removed.length > 0 && (
                      <div className="chat-guardrail-removed">
                        <span className="chat-guardrail-removed-label">
                          Doğrulanamadığı için kaldırılan cümle{removed.length > 1 ? "ler" : ""}
                        </span>
                        <ul>
                          {removed.map((sentence, i) => (
                            <li key={i}>{sentence}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </Alert>
              );
            })}
          </div>
        )}
        <MessageList
          messages={messages}
          streamingText={streamingText}
          loading={loading}
          uploadingDocumentName={documentUploading ? selectedDocument?.file_name ?? "Evrak" : null}
          hasSelectedDocument={Boolean(selectedDocument || selectedDraft)}
          interrupt={interrupt}
          onResume={onResume}
          onSuggestion={setPromptTemplate}
          // A clarify option is answered the same way typing its label
          // would be -- balanced/no-forced-document mirrors the composer's
          // own defaults, since a one-click answer to "taslak mı,
          // revizyon mu?" isn't the moment to also silently change the
          // reasoning level or attach/detach the document.
          onSelectOption={(label) => void onSend(label, "balanced", Boolean(selectedDocument), selectedDraft?.id)}
          planSteps={planSteps}
          nodeOrder={nodeOrder}
          nodeLabels={nodeLabels}
          nodeStatus={nodeStatus}
          nodeMeta={nodeMeta}
          nodeResults={nodeResults}
          toolCalls={toolCalls}
          nodeStartedAt={nodeStartedAt}
          turnStartedAt={turnStartedAt}
          sessionId={activeSessionId}
          onCancel={onCancel}
          onRetryFast={retryFast}
          // Only offer the source view when there is a document to open it
          // against; otherwise citations stay plain labels.
          onCitationClick={selectedDocument ? setCitationTarget : undefined}
        />
        </div>
        <div className="composer-dock">
          {interrupt ? (
            <div className="composer-paused-state" role="status">
              <PauseCircle size={18} />
              <span>
                <strong>Yanıtınız bekleniyor</strong>
                <small>Yukarıdaki soruları tamamladığınızda mesaj alanı yeniden açılır.</small>
              </span>
            </div>
          ) : (
            <ChatComposer
              documents={documents}
              drafts={draftContext.drafts}
              selectedDocument={selectedDocument}
              selectedDraft={selectedDraft}
              loading={loading}
              compacting={compacting}
              contextUsage={contextUsage}
              onCompact={onCompact}
              onSelectDocument={(document) => { setSelectedDraftId(null); onSelectDocument(document); }}
              onSelectDraft={(draft) => {
                onClearDocument();
                if (draft.session_id && draft.session_id !== activeSessionId) {
                  onOpenSession(draft.session_id);
                } else if (!draft.session_id && activeSessionId) {
                  onNewChat();
                }
                setSelectedDraftId(draft.id);
              }}
              onClearDocument={onClearDocument}
              onClearDraft={() => setSelectedDraftId(null)}
              onSend={(text, level, useDocument) => onSend(text, level, useDocument, selectedDraft?.id)}
              promptTemplate={promptTemplate}
              onPromptTemplateConsumed={() => setPromptTemplate(null)}
            />
          )}
        </div>
      </div>
    </div>
  );

  if (!onUploadDocument) return page;
  return (
    <ChatDropZone onUpload={onUploadDocument}>
      {page}
    </ChatDropZone>
  );
}
