import { Bot, FilePenLine, FileSearch, Info, MessageSquare, Route, UserRound } from "lucide-react";
import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import type { ChatMessage, WorkflowLog } from "../../types/chat";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Spinner } from "../../components/Surface";
import { PromptQuestionCard } from "./PromptQuestionCard";
import { DraftMetaStrip } from "./DraftMetaStrip";
import { DiffRevealText } from "./DiffRevealText";

export function MessageList({
  messages,
  streamingText,
  loading,
  logs,
  hasSelectedDocument,
  onSuggestion,
  onSelectOption,
}: {
  messages: ChatMessage[];
  streamingText: string;
  loading: boolean;
  logs: WorkflowLog[];
  hasSelectedDocument: boolean;
  onSuggestion: (prompt: string) => void;
  // Answers a clarify question's option the same way typing its label would
  // -- see app.ai.workflows.planner._try_resolve_pending_clarification.
  // Optional: a caller that doesn't wire clarify options simply never
  // passes questions on a message, so this is never invoked.
  onSelectOption?: (label: string) => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText, logs]);
  return (
    <div className="messages-area">
      {messages.length === 0 && !streamingText ? (
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
                {message.diffSegments ? (
                  <DiffRevealText segments={message.diffSegments} />
                ) : (
                  <ReactMarkdown>{message.text}</ReactMarkdown>
                )}
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
      {loading && !streamingText && (
        <div className="processing-line">
          <Spinner label="İstek işleniyor" />
          {logs[logs.length - 1]?.text ?? "İstek işleniyor…"}
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}
