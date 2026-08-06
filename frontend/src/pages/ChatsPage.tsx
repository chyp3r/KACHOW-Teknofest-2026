import { GitBranch, Plus } from "lucide-react";
import { PageHeader } from "../components/PageHeader";
import { ChatComposer } from "../features/chat/ChatComposer";
import { InterruptPanel } from "../features/chat/InterruptPanel";
import { MessageList } from "../features/chat/MessageList";
import type { ChatMessage, InterruptState, WorkflowLog } from "../types/chat";
import type { DocumentMetadata, ReasoningLevel } from "../types/documents";

export function ChatsPage({
  documents,
  selectedDocument,
  messages,
  streamingText,
  loading,
  logs,
  interrupt,
  workflowOpen,
  onSelectDocument,
  onClearDocument,
  onSend,
  onResume,
  onNewChat,
  onToggleWorkflow,
}: {
  documents: DocumentMetadata[];
  selectedDocument: DocumentMetadata | null;
  messages: ChatMessage[];
  streamingText: string;
  loading: boolean;
  logs: WorkflowLog[];
  interrupt: InterruptState | null;
  workflowOpen: boolean;
  onSelectDocument: (document: DocumentMetadata) => void;
  onClearDocument: () => void;
  onSend: (
    text: string,
    level: ReasoningLevel,
    useDocument: boolean,
  ) => Promise<void>;
  onResume: (
    action: "answer" | "approve" | "revise" | "reject",
    answers: Record<string, string>,
    instructions: string,
  ) => Promise<void>;
  onNewChat: () => void;
  onToggleWorkflow: () => void;
}) {
  return (
    <div className="chat-page">
      <PageHeader
        title="Karar Destek Sohbeti"
        description="Evraklarınızı inceleyin, taslak hazırlayın ve işlem sürecini takip edin."
        actions={
          <>
            <button
              className="button button-secondary workflow-toggle"
              onClick={onToggleWorkflow}
            >
              <GitBranch size={16} />
              {workflowOpen ? "Akışı kapat" : "Karar akışı"}
            </button>
            <button className="button button-primary" onClick={onNewChat}>
              <Plus size={16} />
              Yeni sohbet
            </button>
          </>
        }
      />
      <div className="chat-workspace">
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
        />
        <ChatComposer
          documents={documents}
          selectedDocument={selectedDocument}
          loading={loading || Boolean(interrupt)}
          onSelectDocument={onSelectDocument}
          onClearDocument={onClearDocument}
          onSend={onSend}
        />
      </div>
    </div>
  );
}
