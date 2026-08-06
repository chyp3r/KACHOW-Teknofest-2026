import { Bot, MessageSquare, UserRound } from "lucide-react";
import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import { EmptyState } from "../../components/EmptyState";
import type { ChatMessage, WorkflowLog } from "../../types/chat";

export function MessageList({
  messages,
  streamingText,
  loading,
  logs,
}: {
  messages: ChatMessage[];
  streamingText: string;
  loading: boolean;
  logs: WorkflowLog[];
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText, logs]);
  return (
    <div className="messages-area">
      {messages.length === 0 && !streamingText ? (
        <EmptyState
          icon={MessageSquare}
          title="Sohbete başlayın"
          description="Bir evrak seçin veya genel bir soru yazarak karar desteği alın."
        />
      ) : (
        messages.map((message, index) => (
          <article
            key={`${message.sender}-${index}`}
            className={`chat-message ${message.sender}`}
          >
            <span className="message-avatar">
              {message.sender === "assistant" ? (
                <Bot size={17} />
              ) : (
                <UserRound size={17} />
              )}
            </span>
            <div>
              <header>
                {message.sender === "assistant" ? "KACHOW Asistan" : "Siz"}
              </header>
              <div className="markdown-content">
                <ReactMarkdown>{message.text}</ReactMarkdown>
              </div>
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
          <span className="spinner" />
          {logs[logs.length - 1]?.text ?? "İstek işleniyor…"}
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}
