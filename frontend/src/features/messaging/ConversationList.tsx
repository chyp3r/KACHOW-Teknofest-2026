import { MessageCircle, Plus, Users } from "lucide-react";
import { IconButton } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { ListRow } from "../../components/ListRow";
import { Spinner } from "../../components/Surface";
import type { Conversation } from "../../types/messaging";

function titleFor(conversation: Conversation, currentUserId: string): string {
  if (conversation.kind === "group") return conversation.title || "Adsız grup";
  const other = conversation.participants.find((participant) => participant.user_id !== currentUserId);
  return other?.username ?? "Bilinmeyen kullanıcı";
}

function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return "";
  const diffMinutes = Math.round((Date.now() - value.getTime()) / 60_000);
  if (diffMinutes < 1) return "şimdi";
  if (diffMinutes < 60) return `${diffMinutes} dk`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours} sa`;
  return new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short" }).format(value);
}

export function ConversationList({
  conversations,
  activeConversationId,
  currentUserId,
  loading,
  onSelect,
  onNewConversation,
  onOpenPeople,
}: {
  conversations: Conversation[];
  activeConversationId?: string;
  currentUserId: string;
  loading: boolean;
  onSelect: (conversationId: string) => void;
  onNewConversation: () => void;
  onOpenPeople: () => void;
}) {
  return (
    <div className="conversation-list-panel">
      <header className="conversation-list-header">
        <h2>Mesajlar</h2>
        <div className="conversation-list-actions">
          <IconButton icon={<Users />} aria-label="Kişiler" title="Kişiler" onClick={onOpenPeople} />
          <IconButton icon={<Plus />} aria-label="Yeni konuşma" title="Yeni konuşma" onClick={onNewConversation} />
        </div>
      </header>

      {loading ? (
        <div className="centered-state" role="status">
          <Spinner label="Konuşmalar yükleniyor" />
          Konuşmalar yükleniyor…
        </div>
      ) : conversations.length === 0 ? (
        <EmptyState
          compact
          icon={MessageCircle}
          title="Henüz konuşmanız yok"
          description="Kişiler panelinden birini bularak ilk mesajınızı gönderin."
          primaryAction={<IconButton icon={<Plus />} aria-label="Yeni konuşma başlat" onClick={onNewConversation} />}
        />
      ) : (
        <div className="conversation-list" aria-label="Konuşma listesi">
          {conversations.map((conversation) => {
            const title = titleFor(conversation, currentUserId);
            const selected = conversation.id === activeConversationId;
            return (
              <ListRow
                key={conversation.id}
                selected={selected}
                aria-current={selected ? "page" : undefined}
                leading={conversation.kind === "group" ? <Users /> : <MessageCircle />}
                primary={title}
                secondary={conversation.kind === "group" ? `${conversation.participants.length} üye` : undefined}
                metadata={<time dateTime={conversation.last_message_at ?? undefined}>{relativeTime(conversation.last_message_at)}</time>}
                status={conversation.unread_count > 0 ? <span className="unread-badge">{conversation.unread_count}</span> : undefined}
                onClick={() => onSelect(conversation.id)}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
