import { AlertCircle, History, MessageSquare, Plus, RotateCcw, Search } from "lucide-react";
import { useMemo, useState, type RefObject } from "react";
import type { ChatMessage, ChatSession } from "../../types/chat";
import { Button } from "../../components/Button";
import { Input } from "../../components/FormControls";
import { ListRow } from "../../components/ListRow";
import { EmptyState } from "../../components/EmptyState";
import { Alert, Skeleton, Spinner } from "../../components/Surface";
import { Drawer } from "../../components/Overlay";

const SEARCH_THRESHOLD = 10;
type SessionGroup = "today" | "yesterday" | "older";

const GROUP_LABELS: Record<SessionGroup, string> = {
  today: "Bugün",
  yesterday: "Dün",
  older: "Daha eski",
};

function startOfDay(value: Date): Date {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate());
}

function groupForTimestamp(timestamp: string, now: Date): SessionGroup {
  const value = new Date(timestamp);
  if (Number.isNaN(value.getTime())) return "older";
  const dayDifference = Math.round(
    (startOfDay(now).getTime() - startOfDay(value).getTime()) / 86_400_000,
  );
  if (dayDifference <= 0) return "today";
  if (dayDifference === 1) return "yesterday";
  return "older";
}

function compactTimestamp(timestamp: string, now: Date): string {
  const value = new Date(timestamp);
  if (Number.isNaN(value.getTime())) return "";
  const group = groupForTimestamp(timestamp, now);
  if (group !== "older") {
    return new Intl.DateTimeFormat("tr-TR", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(value);
  }
  return new Intl.DateTimeFormat("tr-TR", {
    day: "numeric",
    month: "short",
    year: value.getFullYear() === now.getFullYear() ? undefined : "numeric",
  }).format(value);
}

function previewForSession(
  session: ChatSession,
  activeSessionId: string | null,
  activeMessages: ChatMessage[],
): string | null {
  if (session.session_id !== activeSessionId) return null;
  const preview = activeMessages[activeMessages.length - 1]?.text.trim();
  if (!preview) return null;
  return preview.replace(/\s+/g, " ");
}

export function ConversationHistoryDrawer({
  sessions,
  activeSessionId,
  activeMessages,
  loading,
  refreshing,
  error,
  returnFocusRef,
  onClose,
  onRetry,
  onNewChat,
  onOpenSession,
}: {
  sessions: ChatSession[];
  activeSessionId: string | null;
  activeMessages: ChatMessage[];
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  returnFocusRef: RefObject<HTMLButtonElement | null>;
  onClose: () => void;
  onRetry: () => Promise<void>;
  onNewChat: () => void;
  onOpenSession: (sessionId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const now = useMemo(() => new Date(), []);
  const showSearch = sessions.length >= SEARCH_THRESHOLD;
  const normalizedQuery = query.trim().toLocaleLowerCase("tr-TR");

  const groupedSessions = useMemo(() => {
    const groups: Record<SessionGroup, ChatSession[]> = {
      today: [],
      yesterday: [],
      older: [],
    };
    sessions
      .filter((session) => {
        if (!normalizedQuery) return true;
        const preview = previewForSession(session, activeSessionId, activeMessages);
        return `${session.title ?? ""} ${preview ?? ""}`
          .toLocaleLowerCase("tr-TR")
          .includes(normalizedQuery);
      })
      .sort(
        (left, right) =>
          new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime(),
      )
      .forEach((session) => {
        groups[groupForTimestamp(session.updated_at, now)].push(session);
      });
    return groups;
  }, [activeMessages, activeSessionId, normalizedQuery, now, sessions]);

  const filteredCount = Object.values(groupedSessions).reduce(
    (total, group) => total + group.length,
    0,
  );

  const startNewChat = () => {
    onClose();
    onNewChat();
  };

  return (
    <Drawer
        open
        id="conversation-history-drawer"
        className="chat-history-drawer"
        backdropClassName="chat-history-backdrop"
        headerClassName="chat-history-header"
        bodyClassName="chat-history-body"
        title="Sohbet geçmişi"
        closeLabel="Sohbet geçmişini kapat"
        onClose={onClose}
        returnFocusRef={returnFocusRef}
      >
          {error ? (
            <Alert className="chat-history-error" variant="error" icon={<AlertCircle />} action={<Button variant="secondary" size="sm" leadingIcon={<RotateCcw />} onClick={() => void onRetry()}>Tekrar dene</Button>}>{error}</Alert>
          ) : loading ? (
            <div className="chat-history-skeletons" role="status" aria-label="Sohbet geçmişi yükleniyor">
              {[0, 1, 2, 3].map((row) => (
                <Skeleton className="chat-history-skeleton" key={row} lines={2} />
              ))}
            </div>
          ) : sessions.length === 0 ? (
            <EmptyState compact icon={History} title="Henüz kayıtlı sohbetiniz yok" description="Yeni bir sohbet başlattığınızda geçmişiniz burada görünür." primaryAction={<Button leadingIcon={<Plus />} onClick={startNewChat}>Yeni sohbet başlat</Button>} />
          ) : (
            <>
              {showSearch && (
                <Input
                  fieldClassName="chat-history-search"
                  leadingIcon={<Search />}
                  aria-label="Sohbet geçmişinde ara"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Sohbetlerde ara"
                  />
              )}
              {refreshing && (
                <div className="chat-history-refresh" role="status">
                  <Spinner size="xs" label="Sohbet geçmişi güncelleniyor" /> Güncelleniyor
                </div>
              )}
              {filteredCount === 0 ? (
                <p className="chat-history-no-results">Aramanızla eşleşen sohbet bulunamadı.</p>
              ) : (
                <div className="chat-session-groups" aria-label="Sohbet geçmişi listesi">
                  {(Object.keys(GROUP_LABELS) as SessionGroup[]).map((group) => {
                    const groupSessions = groupedSessions[group];
                    if (groupSessions.length === 0) return null;
                    return (
                      <section className="chat-session-group" key={group}>
                        <h3>{GROUP_LABELS[group]}</h3>
                        <div className="chat-sessions">
                          {groupSessions.map((session) => {
                            const selected = session.session_id === activeSessionId;
                            const preview = previewForSession(
                              session,
                              activeSessionId,
                              activeMessages,
                            );
                            return (
                              <ListRow
                                key={session.session_id}
                                className={selected ? "active" : ""}
                                aria-current={selected ? "page" : undefined}
                                onClick={() => onOpenSession(session.session_id)}
                                selected={selected}
                                leading={<MessageSquare />}
                                primary={session.title || "Yeni sohbet"}
                                secondary={preview}
                                metadata={<time dateTime={session.updated_at}>{compactTimestamp(session.updated_at, now)}</time>}
                              />
                            );
                          })}
                        </div>
                      </section>
                    );
                  })}
                </div>
              )}
            </>
          )}
    </Drawer>
  );
}
