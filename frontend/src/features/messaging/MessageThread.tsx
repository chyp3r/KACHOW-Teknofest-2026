import { ArrowUp, MessageCircle } from "lucide-react";
import { useEffect, useRef } from "react";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Spinner } from "../../components/Surface";
import type { Message } from "../../types/messaging";

function formatTime(iso: string): string {
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return "";
  return new Intl.DateTimeFormat("tr-TR", { hour: "2-digit", minute: "2-digit" }).format(value);
}

export function MessageThread({
  messages,
  currentUserId,
  loading,
  loadingOlder,
  hasMore,
  onLoadOlder,
}: {
  messages: Message[];
  currentUserId: string;
  loading: boolean;
  loadingOlder: boolean;
  hasMore: boolean;
  onLoadOlder: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastMessageId = messages[messages.length - 1]?.id;

  useEffect(() => {
    const container = scrollRef.current;
    if (!container || !lastMessageId) return;
    container.scrollTop = container.scrollHeight;
  }, [lastMessageId]);

  if (loading) {
    return (
      <div className="centered-state message-thread-loading" role="status">
        <Spinner label="Mesajlar yükleniyor" />
        Mesajlar yükleniyor…
      </div>
    );
  }

  if (messages.length === 0) {
    return (
      <EmptyState
        compact
        icon={MessageCircle}
        title="Henüz mesaj yok"
        description="Bu konuşmada ilk mesajı gönderin."
      />
    );
  }

  return (
    <div className="message-thread" ref={scrollRef}>
      {hasMore && (
        <div className="message-thread-load-older">
          <Button variant="ghost" size="sm" leadingIcon={<ArrowUp />} loading={loadingOlder} onClick={onLoadOlder}>
            Daha eski mesajları yükle
          </Button>
        </div>
      )}
      {messages.map((message) => {
        const own = message.sender_id === currentUserId;
        if (message.kind === "system") {
          return (
            <p key={message.id} className="message-system-line">
              {message.body}
            </p>
          );
        }
        return (
          <article key={message.id} className={`message-bubble ${own ? "own" : "other"}`}>
            <div className="message-bubble-body">
              {!own && <header>{message.sender_username ?? "Bilinmeyen kullanıcı"}</header>}
              <p>{message.body}</p>
              <time dateTime={message.created_at}>{formatTime(message.created_at)}</time>
            </div>
          </article>
        );
      })}
    </div>
  );
}
