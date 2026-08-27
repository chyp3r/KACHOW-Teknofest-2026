import { Bot, FilePenLine, FileSearch, Info, MessageCircle, MessageSquare, Route, Sparkles, UploadCloud, UserRound } from "lucide-react";
import { useCallback, useEffect, useRef } from "react";
import type { UIEvent } from "react";
import type {
  ChatMessage,
  InterruptState,
  ToolCallEvent,
  WorkflowNodeStatus,
} from "../../types/chat";
import { Button } from "../../components/Button";
import { Accordion } from "../../components/Accordion";
import { MarkdownMessage } from "./MarkdownMessage";
import { EmptyState } from "../../components/EmptyState";
import { Spinner } from "../../components/Surface";
import { PromptQuestionCard } from "./PromptQuestionCard";
import { DraftMetaStrip } from "./DraftMetaStrip";
import { FeedbackButtons } from "./FeedbackButtons";
import { InterruptPanel } from "./InterruptPanel";
import { ThinkingBubble } from "./ThinkingBubble";
import { ResolvedPromptCard } from "./ResolvedPromptCard";
import type { PromptAnswers } from "./PromptQuestionCard";
import type { FeedbackTargetKind } from "../../types/feedback";
import { AnimatedMessageText } from "./AnimatedMessageText";

// What a message's vote should be filed under, plus a small context
// snapshot worth carrying alongside it (see FeedbackModel.context) --
// derived from the same `details.draft`/`details.intent` shape
// DraftMetaStrip already reads, not a new field the backend has to add.
function feedbackTargetFor(message: ChatMessage): {
  targetKind: FeedbackTargetKind;
  context?: Record<string, unknown>;
} {
  const draft = message.details?.draft as
    | { status?: string; combined_score?: number }
    | undefined;
  const intent = message.details?.intent as string | undefined;
  if (draft) {
    return {
      targetKind: intent === "revise" ? "revision" : "draft",
      context: { status: draft.status, combined_score: draft.combined_score },
    };
  }
  return { targetKind: "assist_reply" };
}

export function MessageList({
  messages,
  streamingText,
  loading,
  uploadingDocumentName,
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
  sessionId,
}: {
  messages: ChatMessage[];
  streamingText: string;
  loading: boolean;
  uploadingDocumentName?: string | null;
  hasSelectedDocument: boolean;
  // Rendered as the last bubble in the scrolling conversation (see the
  // interrupt-message article below) rather than as a standalone panel
  // pinned above it -- a routine approval/question/writing-brief ask is
  // part of the exchange, not a modal breaking out of it. Optional: a
  // caller with no human-in-the-loop gate wired up simply never passes one.
  interrupt?: InterruptState | null;
  onResume?: (
    action: "answer" | "approve" | "revise" | "reject" | "select",
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
  // Carried on a vote for traceability only (FeedbackModel.session_id) --
  // absent for a caller with no session concept, in which case a vote
  // simply carries no session link.
  sessionId?: string | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);
  const scrollToBottom = useCallback(() => {
    const container = containerRef.current;
    if (!container || !pinnedRef.current) return;
    requestAnimationFrame(() => {
      container.scrollTop = container.scrollHeight;
    });
  }, []);
  useEffect(() => {
    scrollToBottom();
  }, [messages, streamingText, interrupt, uploadingDocumentName, scrollToBottom]);
  const handleScroll = (event: UIEvent<HTMLDivElement>) => {
    const el = event.currentTarget;
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96;
  };
  const visibleMessages = messages.filter((message) => {
    if (!interrupt || message.sender !== "assistant") return true;
    return !message.details?.interrupt;
  });
  return (
    <div className="messages-area" ref={containerRef} onScroll={handleScroll}>
      {visibleMessages.length === 0 && !streamingText && !interrupt && !uploadingDocumentName ? (
        <EmptyState className="chat-empty-state" icon={MessageSquare} title="Nasıl yardımcı olabilirim?" description={hasSelectedDocument
          ? "Seçili içerik üzerinde çalışın veya resmî yazışma süreciniz için destek alın."
          : "Bir soru sorun, birlikte fikir üretin veya KACHOW'un neler yapabildiğini keşfedin."
        } primaryAction={
          <div className="suggested-actions" aria-label="Önerilen başlangıçlar">
            {hasSelectedDocument ? (
              <>
                <Button variant="secondary" leadingIcon={<FileSearch />} onClick={() => onSuggestion("Seçili evrakı incele ve önemli noktaları özetle.")}>
                  <span><strong>Seçili içeriği incele</strong><small>Önemli noktaları ve eksikleri özetle</small></span>
                </Button>
                <Button variant="secondary" leadingIcon={<FilePenLine />} onClick={() => onSuggestion("Seçili içerik için resmî yazı taslağı hazırla.")}>
                  <span><strong>Resmî taslak hazırla</strong><small>Uygun yazışma biçimini kullan</small></span>
                </Button>
                <Button variant="secondary" leadingIcon={<Route />} onClick={() => onSuggestion("Seçili içerik için uygun hedef birimi gerekçesiyle öner.")}>
                  <span><strong>Hedef birim öner</strong><small>Son kararı vermeden öneri oluştur</small></span>
                </Button>
              </>
            ) : (
              <>
                <Button variant="secondary" leadingIcon={<Sparkles />} onClick={() => onSuggestion("Neler yapabildiğini ve bana hangi konularda yardımcı olabileceğini kısaca anlat.")}>
                  <span><strong>Neler yapabilirsin?</strong><small>KACHOW'un yeteneklerini keşfet</small></span>
                </Button>
                <Button variant="secondary" leadingIcon={<MessageCircle />} onClick={() => onSuggestion("Merhaba! Bugün nasılsın?")}>
                  <span><strong>Sohbete başlayalım</strong><small>Selam ver ve asistanla tanış</small></span>
                </Button>
              </>
            )}
          </div>
        } />
      ) : (
        visibleMessages.map((message, index) => (
          <article
            key={`${message.sender}-${index}`}
            className={`chat-message ${message.sender}${
              message.kind === "notice" ? " notice-message" : ""
            }${message.resolvedPrompt ? " resolved-prompt-message" : ""}`}
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
              {message.text && (
                <AnimatedMessageText
                  text={message.text}
                  animate={message.animate}
                  onProgress={scrollToBottom}
                />
              )}
              {message.resolvedPrompt && (
                <ResolvedPromptCard interaction={message.resolvedPrompt} />
              )}
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
                <Accordion className="message-logs" title={`Akış günlüğü (${message.logs.length})`}>
                  {message.logs.map((log, logIndex) => (
                    <p key={logIndex}>
                      <time>{log.time}</time>
                      {log.text}
                    </p>
                  ))}
                </Accordion>
              ) : null}
              {message.sender === "assistant" && message.kind !== "notice" && message.text && (
                <FeedbackButtons
                  {...feedbackTargetFor(message)}
                  content={message.text}
                  sessionId={sessionId ?? undefined}
                  messageId={message.id}
                />
              )}
            </div>
          </article>
        ))
      )}
      {uploadingDocumentName && (
        <article className="chat-message assistant notice-message document-upload-message" role="status" aria-live="polite">
          <span className="message-avatar">
            <UploadCloud size={17} />
          </span>
          <div>
            <header>Evrak yükleniyor</header>
            <div className="document-upload-message-copy">
              <Spinner size="sm" label={`${uploadingDocumentName} yükleniyor ve analiz ediliyor`} />
              <p><strong>{uploadingDocumentName}</strong> yükleniyor ve analiz ediliyor…</p>
            </div>
          </div>
        </article>
      )}
      {streamingText && (
        <article className="chat-message assistant">
          <span className="message-avatar">
            <Bot size={17} />
          </span>
          <div>
            <header>KACHOW Asistan</header>
            <div className="markdown-content">
              <MarkdownMessage text={streamingText} />
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
            {/* Keyed on interrupt_id so a new interrupt on the same mount
                point -- a brief-gate re-ask, missing_information following
                a writing_brief, or a second draft's gate later in the same
                session -- fully remounts this panel instead of reusing it.
                Without this, InterruptPanel's own useState (instructions/
                rejectReason/quickPicks/revisionNote) and PromptQuestionCard's
                nested stepIndex/answers carried the *previous* interrupt's
                values into the new one. */}
            <InterruptPanel key={interrupt.interruptId} interrupt={interrupt} loading={loading} onResume={onResume} />
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
