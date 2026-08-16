import { MessageCircle, Settings } from "lucide-react";
import { useRef, useState } from "react";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { IconButton } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { ConversationList } from "../features/messaging/ConversationList";
import { GroupParticipantsPanel } from "../features/messaging/GroupParticipantsPanel";
import { MessageComposer } from "../features/messaging/MessageComposer";
import { MessageThread } from "../features/messaging/MessageThread";
import { NewConversationDialog } from "../features/messaging/NewConversationDialog";
import { UserSearchDrawer } from "../features/messaging/UserSearchDrawer";
import { useConversations } from "../hooks/useConversations";
import { useMessageThread } from "../hooks/useMessageThread";

export function MessagesPage({
  currentUserId,
  activeConversationId,
  onSelectConversation,
}: {
  currentUserId: string;
  activeConversationId?: string;
  onSelectConversation: (conversationId: string) => void;
}) {
  const conversations = useConversations();
  const thread = useMessageThread(activeConversationId ?? null);
  const [newConversationOpen, setNewConversationOpen] = useState(false);
  const [peopleDrawerOpen, setPeopleDrawerOpen] = useState(false);
  const [participantsPanelOpen, setParticipantsPanelOpen] = useState(false);
  const [openingDmUserId, setOpeningDmUserId] = useState<string | null>(null);
  const [removingParticipantId, setRemovingParticipantId] = useState<string | null>(null);
  const peopleButtonRef = useRef<HTMLButtonElement>(null);

  const activeConversation = conversations.conversations.find(
    (item) => item.id === activeConversationId,
  );

  const openDm = async (userId: string) => {
    setOpeningDmUserId(userId);
    try {
      const conversation = await conversations.openDm(userId);
      onSelectConversation(conversation.id);
    } finally {
      setOpeningDmUserId(null);
    }
  };

  const markThreadRead = () => {
    if (activeConversation && activeConversation.unread_count > 0) void thread.markRead();
  };

  return (
    <div className="page messages-page">
      <div className="messages-layout">
        <ConversationList
          conversations={conversations.conversations}
          activeConversationId={activeConversationId}
          currentUserId={currentUserId}
          loading={conversations.loading}
          onSelect={onSelectConversation}
          onNewConversation={() => setNewConversationOpen(true)}
          onOpenPeople={() => setPeopleDrawerOpen(true)}
        />

        <div className="message-thread-panel">
          {conversations.errorObject && <ApiErrorNotice error={conversations.errorObject} />}
          {!activeConversation ? (
            <EmptyState
              icon={MessageCircle}
              title="Bir konuşma seçin"
              description="Soldaki listeden bir konuşma açın veya yeni bir konuşma başlatın."
            />
          ) : (
            <>
              <header className="message-thread-header">
                <h2>
                  {activeConversation.kind === "group"
                    ? activeConversation.title || "Adsız grup"
                    : activeConversation.participants.find((participant) => participant.user_id !== currentUserId)
                        ?.username ?? "Bilinmeyen kullanıcı"}
                </h2>
                {activeConversation.kind === "group" && (
                  <IconButton
                    icon={<Settings />}
                    aria-label="Grup üyelerini yönet"
                    title="Grup üyelerini yönet"
                    onClick={() => {
                      markThreadRead();
                      setParticipantsPanelOpen(true);
                    }}
                  />
                )}
              </header>
              {thread.errorObject && <ApiErrorNotice error={thread.errorObject} />}
              <MessageThread
                messages={thread.messages}
                currentUserId={currentUserId}
                loading={thread.loading}
                loadingOlder={thread.loadingOlder}
                hasMore={thread.hasMore}
                onLoadOlder={() => void thread.loadOlder()}
              />
              <MessageComposer
                disabled={
                  activeConversation.participants.find((participant) => participant.user_id === currentUserId)
                    ?.left_at != null
                }
                sending={thread.sending}
                onSend={async (body) => {
                  await thread.send(body);
                  markThreadRead();
                }}
              />
            </>
          )}
        </div>
      </div>

      <NewConversationDialog
        open={newConversationOpen}
        onClose={() => setNewConversationOpen(false)}
        onOpenDm={(userId) => void openDm(userId)}
        openingDmUserId={openingDmUserId}
        onCreateGroup={async (title, participantIds) => {
          const conversation = await conversations.createGroup(title, participantIds);
          onSelectConversation(conversation.id);
        }}
        creatingGroup={conversations.creatingGroup}
      />

      <UserSearchDrawer
        open={peopleDrawerOpen}
        onClose={() => setPeopleDrawerOpen(false)}
        returnFocusRef={peopleButtonRef}
        mode="message"
        messagingUserId={openingDmUserId}
        onMessage={(userId) => {
          setPeopleDrawerOpen(false);
          void openDm(userId);
        }}
      />

      {activeConversation && activeConversation.kind === "group" && (
        <GroupParticipantsPanel
          open={participantsPanelOpen}
          onClose={() => setParticipantsPanelOpen(false)}
          conversation={activeConversation}
          currentUserId={currentUserId}
          onAddParticipants={async (userIds) => {
            await conversations.addParticipants(activeConversation.id, userIds);
          }}
          addingParticipants={conversations.addingParticipants}
          onRemoveParticipant={async (userId) => {
            setRemovingParticipantId(userId);
            try {
              await conversations.removeParticipant(activeConversation.id, userId);
            } finally {
              setRemovingParticipantId(null);
            }
          }}
          removingParticipantId={removingParticipantId}
          onLeave={async () => {
            await conversations.removeParticipant(activeConversation.id, currentUserId);
            setParticipantsPanelOpen(false);
          }}
        />
      )}
    </div>
  );
}
