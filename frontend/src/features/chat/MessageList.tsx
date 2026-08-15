import { Bot, FilePenLine, FileSearch, Info, MessageSquare, Route, UserRound } from "lucide-react";
import { useEffect, useRef } from "react";
import type { UIEvent } from "react";
import ReactMarkdown from "react-markdown";
import type {
  ChatMessage,
  InterruptState,
  ToolCallEvent,
  WorkflowNodeStatus,
} from "../../types/chat";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { PromptQuestionCard } from "./PromptQuestionCard";
import { DraftMetaStrip } from "./DraftMetaStrip";
import { InterruptPanel } from "./InterruptPanel";
import { ThinkingBubble } from "./ThinkingBubble";
import type { PromptAnswers } from "./PromptQuestionCard";

export function MessageList({
  messages,
  streamingText,
  loading,
  hasSelectedDocument,
  interrupt,
  onResume,
  onSuggestion,
  onSelectOption,
  planSteps = [],
  nodeOrder = [],
  nodeLabels = {},
  nodeStatus = {},
  nodeMeta = {},
  nodeResults = {},
  toolCalls = [],
  nodeStartedAt = {},
  turnStartedAt = null,
  onCancel,
  onRetryFast,
}: {
  messages: ChatMessage[];
  streamingText: string;
  loading: boolean;
  hasSelectedDocument: boolean;
  // Rendered as the last bubble in the scrolling conversation (see the
  // interrupt-message article below) rather than as a standalone panel
  // pinned above it -- a routine approval/question/writing-brief ask is
  // part of the exchange, not a modal breaking out of it. Optional: a
  // caller with no human-in-the-loop gate wired up simply never passes one.
  interrupt?: InterruptState | null;
  onResume?: (
    action: "answer" | "approve" | "revise" | "reject",
    answers: PromptAnswers,
    instructions: string,
    reason?: string,
  ) => Promise<void>;
  onSuggestion: (prompt: string) => void;
  // Answers a clarify question's option the same way typing its label would
  // -- see app.ai.workflows.planner._try_resolve_pending_clarification.
  // Optional: a caller that doesn't wire clarify options simply never
  // passes questions on a message, so this is never invoked.
  onSelectOption?: (label: string) => void;
  // The rest are ThinkingBubble's own live-progress data, threaded straight
  // through from useChatWorkflow -- optional so a caller with no workflow
  // wiring (tests, a future minimal chat surface) still renders the plain
  // loading state ThinkingBubble falls back to with empty defaults.
  planSteps?: string[];
  nodeOrder?: string[];
  nodeLabels?: Record<string, string>;
  nodeStatus?: Record<string, WorkflowNodeStatus>;
  nodeMeta?: Record<string, Record<string, unknown>>;
  nodeResults?: Record<string, Record<string, unknown>>;
  toolCalls?: ToolCallEvent[];
  nodeStartedAt?: Record<string, number>;
  turnStartedAt?: number | null;
  onCancel?: () => void;
  onRetryFast?: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !pinnedRef.current) return;
    const frame = requestAnimationFrame(() => {
      container.scrollTop = container.scrollHeight;
    });
    return () => cancelAnimationFrame(frame);
  }, [messages, streamingText, interrupt]);
  const handleScroll = (event: UIEvent<HTMLDivElement>) => {
    const el = event.currentTarget;
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96;
  };
  return (
    <div className="messages-area" ref={containerRef} onScroll={handleScroll}>
      {messages.length === 0 && !streamingText && !interrupt ? (
        <EmptyState className="chat-empty-state" icon={MessageSquare} title="Nasıl yardımcı olabilirim?" description="Bir evrak üzerinde çalışın veya resmî yazışma süreciniz için destek alın." primaryAction={
          <div className="suggested-actions" aria-label="Önerilen başlangıçlar">
            {hasSelectedDocument && (
              <Button variant="secondary" leadingIcon={<FileSearch />} onClick={() => onSuggestion("Seçili evrakı incele ve önemli noktaları özetle.")}>
                <span><strong>Seçili evrakı incele</strong><small>Önemli noktaları ve eksikleri özetle</small></span>
              </Button>
            )}
            <Button variant="secondary" leadingIcon={<FilePenLine />} onClick={() => onSuggestion("Seçili evrak için resmî yazı taslağı hazırla.")}>
              <span><strong>Resmî taslak hazırla</strong><small>Uygun yazışma biçimini kullan</small></span>
            </Button>
            <Button variant="secondary" leadingIcon={<Route />} onClick={() => onSuggestion("Bu içerik için uygun hedef birimi gerekçesiyle öner.")}>
              <span><strong>Hedef birim öner</strong><small>Son kararı vermeden öneri oluştur</small></span>
            </Button>
          </div>
        } />
      ) : (
        messages.map((message, index) => (
          <article
            key={`${message.sender}-${index}`}
            className={`chat-message ${message.sender}${
              message.kind === "notice" ? " notice-message" : ""
            }`}
          >
            <span className="message-avatar">
              {message.kind === "notice" ? (
                <Info size={17} />
              ) : message.sender === "assistant" ? (
                <Bot size={17} />
              ) : (
                <UserRound size={17} />
              )}
            </span>
            <div>
              <header>
                {message.kind === "notice"
                  ? "Bilgilendirme"
                  : message.sender === "assistant"
                    ? "KACHOW Asistan"
                    : "Siz"}
              </header>
              <div className="markdown-content">
                <ReactMarkdown>{message.text}</ReactMarkdown>
              </div>
              <DraftMetaStrip details={message.details} />
              {message.questions?.length ? (
                <PromptQuestionCard
                  questions={message.questions}
                  loading={loading}
                  submitLabel="Gönder"
                  onSubmit={(answers) => {
                    const [question] = message.questions ?? [];
                    if (!question) return;
                    const selected = answers[question.key];
                    const value = Array.isArray(selected) ? selected[0] : selected;
                    const label =
                      question.options.find((option) => option.value === value)?.label ?? value ?? "";
                    onSelectOption?.(label);
                  }}
                />
              ) : null}
              {message.logs?.length ? (
                <details className="message-logs">
                  <summary>Akış günlüğü ({message.logs.length})</summary>
                  {message.logs.map((log, logIndex) => (
                    <p key={logIndex}>
                      <time>{log.time}</time>
                      {log.text}
                    </p>
                  ))}
                </details>
              ) : null}
            </div>
          </article>
        ))
      )}
      {streamingText && (
        <article className="chat-message assistant">
          <span className="message-avatar">
            <Bot size={17} />
          </span>
          <div>
            <header>KACHOW Asistan</header>
            <div className="markdown-content">
              <ReactMarkdown>{streamingText}</ReactMarkdown>
              <span className="streaming-caret" />
            </div>
          </div>
        </article>
      )}
      {interrupt && onResume && (
        <article className="chat-message assistant interrupt-message">
          <span className="message-avatar">
            <Bot size={17} />
          </span>
          <div>
            {/* Distinct from the loading spinner on purpose: the run is not
                "thinking" here, it is stopped, waiting on the user -- see
                ThinkingBubble below for the "still working" state. */}
            <p className="interrupt-paused-banner">Yanıtınız bekleniyor — akış duraklatıldı.</p>
            <InterruptPanel interrupt={interrupt} loading={loading} onResume={onResume} />
          </div>
        </article>
      )}
      {loading && !streamingText && !interrupt && (
        <ThinkingBubble
          planSteps={planSteps}
          nodeOrder={nodeOrder}
          nodeLabels={nodeLabels}
          nodeStatus={nodeStatus}
          nodeMeta={nodeMeta}
          nodeResults={nodeResults}
          toolCalls={toolCalls}
          nodeStartedAt={nodeStartedAt}
          turnStartedAt={turnStartedAt}
          onCancel={onCancel}
          onRetryFast={onRetryFast}
        />
      )}
    </div>
  );
}
