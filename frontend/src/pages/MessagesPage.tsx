import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, MessageCircle, Paperclip, Settings } from "lucide-react";
import { useRef, useState } from "react";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { IconButton } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { ConversationList } from "../features/messaging/ConversationList";
import { GroupParticipantsPanel } from "../features/messaging/GroupParticipantsPanel";
import { MessageComposer } from "../features/messaging/MessageComposer";
import { MessageThread } from "../features/messaging/MessageThread";
import { NewConversationDialog } from "../features/messaging/NewConversationDialog";
import { SendArtifactDialog } from "../features/messaging/SendArtifactDialog";
import { UserSearchDrawer } from "../features/messaging/UserSearchDrawer";
import { useConversations } from "../hooks/useConversations";
import { useMessageThread } from "../hooks/useMessageThread";
import { queryKeys } from "../query/queryKeys";

export function MessagesPage({
  currentUserId,
  activeConversationId,
  onSelectConversation,
  onCloseConversation,
}: {
  currentUserId: string;
  activeConversationId?: string;
  onSelectConversation: (conversationId: string) => void;
  onCloseConversation: () => void;
}) {
  const queryClient = useQueryClient();
  const conversations = useConversations();
  const thread = useMessageThread(activeConversationId ?? null);
  const [newConversationOpen, setNewConversationOpen] = useState(false);
  const [peopleDrawerOpen, setPeopleDrawerOpen] = useState(false);
  const [participantsPanelOpen, setParticipantsPanelOpen] = useState(false);
  const [sendArtifactOpen, setSendArtifactOpen] = useState(false);
  const [openingDmUserId, setOpeningDmUserId] = useState<string | null>(null);
  const [removingParticipantId, setRemovingParticipantId] = useState<string | null>(null);
  const peopleButtonRef = useRef<HTMLButtonElement>(null);

  const activeConversation = conversations.conversations.find(
    (item) => item.id === activeConversationId,
  );
  // Transfers are 1:1 (`POST /transfers/send` takes a single recipient_id)
  // -- only a DM's other participant is a valid target, never a group.
  const dmRecipientId =
    activeConversation?.kind === "dm"
      ? activeConversation.participants.find((participant) => participant.user_id !== currentUserId)?.user_id
      : undefined;
  const groupRecipientIds = activeConversation?.kind === "group"
    ? activeConversation.participants.filter((participant) => participant.user_id !== currentUserId && participant.left_at == null).map((participant) => participant.user_id)
    : undefined;

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
      <div className={`messages-layout ${activeConversation ? "has-active-conversation" : ""}`}>
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
                <IconButton
                  className="message-thread-back"
                  icon={<ChevronLeft />}
                  aria-label="Konuşma listesine dön"
                  onClick={onCloseConversation}
                />
                <h2>
                  {activeConversation.kind === "group"
                    ? activeConversation.title || "Adsız grup"
                    : activeConversation.participants.find((participant) => participant.user_id !== currentUserId)
                        ?.username ?? "Bilinmeyen kullanıcı"}
                </h2>
                <div className="message-thread-header-actions">
                  {(dmRecipientId || groupRecipientIds?.length) && (
                    <IconButton
                      icon={<Paperclip />}
                      aria-label="Taslak veya evrak gönder"
                      title="Taslak veya evrak gönder"
                      onClick={() => setSendArtifactOpen(true)}
                    />
                  )}
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
                </div>
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

      {(dmRecipientId || groupRecipientIds?.length) && (
        <SendArtifactDialog
          open={sendArtifactOpen}
          onClose={() => setSendArtifactOpen(false)}
          recipientId={dmRecipientId}
          recipientIds={groupRecipientIds}
          onSent={() => {
            // The sender's own thread never receives its own message via
            // the messaging SSE stream (see ConversationService.
            // _notify_recipients -- it explicitly skips the sender), so
            // this refetch is what actually surfaces the new artifact
            // message and the conversation list's updated last_message_at
            // for the sender's own view.
            if (activeConversation) {
              void queryClient.invalidateQueries({
                queryKey: queryKeys.conversationMessages(activeConversation.id),
              });
            }
            void queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
          }}
        />
      )}

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
