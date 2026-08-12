import { useRef, useState } from "react";
import { AlertCircle, GitBranch, History, Plus, RotateCcw, Square } from "lucide-react";
import { PageHeader } from "../components/PageHeader";
import { ChatComposer } from "../features/chat/ChatComposer";
import { ChatDropZone } from "../features/chat/ChatDropZone";
import { ConversationHistoryDrawer } from "../features/chat/ConversationHistoryDrawer";
import { InterruptPanel } from "../features/chat/InterruptPanel";
import { MessageList } from "../features/chat/MessageList";
import type {
  ChatMessage,
  ChatSession,
  GuardrailEvent,
  InterruptState,
  WorkflowLog,
} from "../types/chat";
import type { DocumentMetadata, ReasoningLevel } from "../types/documents";
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
  selectedDocument,
  messages,
  streamingText,
  loading,
  logs,
  guardrailEvents,
  interrupt,
  workflowOpen,
  historyOpen,
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
  selectedDocument: DocumentMetadata | null;
  messages: ChatMessage[];
  streamingText: string;
  loading: boolean;
  logs: WorkflowLog[];
  guardrailEvents: GuardrailEvent[];
  interrupt: InterruptState | null;
  workflowOpen: boolean;
  historyOpen: boolean;
  onSelectDocument: (document: DocumentMetadata) => void;
  onClearDocument: () => void;
  onSend: (
    text: string,
    level: ReasoningLevel,
    useDocument: boolean,
  ) => Promise<void>;
  onResume: (
    action: "answer" | "approve" | "revise" | "reject",
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
  const [promptTemplate, setPromptTemplate] = useState<string | null>(null);
  const historyTriggerRef = useRef<HTMLButtonElement>(null);

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
        primaryAction={<Button leadingIcon={<Plus />} onClick={onNewChat}>Yeni sohbet</Button>}
      />
      {historyOpen && (
        <ConversationHistoryDrawer
          sessions={sessions}
          activeSessionId={activeSessionId}
          activeMessages={messages}
          loading={sessionsLoading}
          refreshing={sessionsRefreshing}
          error={sessionsError}
          returnFocusRef={historyTriggerRef}
          onClose={onCloseHistory}
          onRetry={onRetrySessions}
          onNewChat={onNewChat}
          onOpenSession={onOpenSession}
        />
      )}
      <div className="chat-workspace">
        <div className="chat-content">
        {historyError && !historyOpen && (
          <Alert variant="error" icon={<AlertCircle />} action={<Button variant="ghost" size="sm" leadingIcon={<RotateCcw />} onClick={() => void onRetryHistory()}>Tekrar dene</Button>}>{historyError}</Alert>
        )}
        {historyLoading && <div className="processing-line"><Spinner label="Sohbet yükleniyor" />Sohbet yükleniyor…</div>}
        {guardrailEvents.length > 0 && (
          <div className="chat-guardrail-stack">
            {guardrailEvents.map((guardrail, index) => (
              <Alert
                variant={guardrail.decision === "blocked" ? "error" : "warning"}
                title={`Güvenlik kontrolü: ${guardrail.decision}`}
                key={`${guardrail.stage}-${guardrail.kind}-${index}`}
              >
                <span>{guardrail.reasons.join(" · ")}</span>
              </Alert>
            ))}
          </div>
        )}
        {interrupt && (
          <InterruptPanel
            interrupt={interrupt}
            loading={loading}
            onResume={onResume}
          />
        )}
        <MessageList
          messages={messages}
          streamingText={streamingText}
          loading={loading}
          logs={logs}
          hasSelectedDocument={Boolean(selectedDocument)}
          onSuggestion={setPromptTemplate}
          // A clarify option is answered the same way typing its label
          // would be -- balanced/no-forced-document mirrors the composer's
          // own defaults, since a one-click answer to "taslak mı,
          // revizyon mu?" isn't the moment to also silently change the
          // reasoning level or attach/detach the document.
          onSelectOption={(label) => void onSend(label, "balanced", Boolean(selectedDocument))}
        />
        {loading && (
          <Button className="cancel-stream-button" variant="ghost" size="sm" leadingIcon={<Square />} onClick={onCancel}>İşlemi durdur</Button>
        )}
        </div>
        <div className="composer-dock">
          <ChatComposer
          documents={documents}
          selectedDocument={selectedDocument}
          loading={loading || Boolean(interrupt)}
          onSelectDocument={onSelectDocument}
          onClearDocument={onClearDocument}
          onSend={onSend}
          promptTemplate={promptTemplate}
          onPromptTemplateConsumed={() => setPromptTemplate(null)}
          />
        </div>
      </div>
    </div>
  );

  if (!onUploadDocument) return page;
  return (
    <ChatDropZone uploading={documentUploading} onUpload={onUploadDocument}>
      {page}
    </ChatDropZone>
  );
}
