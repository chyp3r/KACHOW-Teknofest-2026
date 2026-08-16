import { Crown, LogOut, UserMinus, UserPlus } from "lucide-react";
import { type RefObject, useState } from "react";
import { Button, IconButton } from "../../components/Button";
import { Drawer } from "../../components/Overlay";
import type { Conversation } from "../../types/messaging";
import { PersonPickerBody } from "./PersonPickerBody";

export function GroupParticipantsPanel({
  open,
  onClose,
  returnFocusRef,
  conversation,
  currentUserId,
  onAddParticipants,
  addingParticipants,
  onRemoveParticipant,
  removingParticipantId,
  onLeave,
}: {
  open: boolean;
  onClose: () => void;
  returnFocusRef?: RefObject<HTMLElement | null>;
  conversation: Conversation;
  currentUserId: string;
  onAddParticipants: (userIds: string[]) => Promise<void>;
  addingParticipants: boolean;
  onRemoveParticipant: (userId: string) => Promise<void>;
  removingParticipantId: string | null;
  onLeave: () => Promise<void>;
}) {
  const [addMode, setAddMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const canManage = conversation.role_in_conversation === "owner";
  const activeParticipants = conversation.participants.filter((participant) => !participant.left_at);

  const toggleSelect = (userId: string) => {
    setSelectedIds((current) =>
      current.includes(userId) ? current.filter((id) => id !== userId) : [...current, userId],
    );
  };

  const confirmAdd = async () => {
    if (selectedIds.length === 0) return;
    await onAddParticipants(selectedIds);
    setAddMode(false);
    setSelectedIds([]);
  };

  return (
    <Drawer
      open={open}
      id="group-participants-panel"
      className="group-participants-panel"
      title={addMode ? "Üye ekle" : "Grup üyeleri"}
      closeLabel="Grup üyeleri panelini kapat"
      onClose={() => {
        onClose();
        setAddMode(false);
        setSelectedIds([]);
      }}
      returnFocusRef={returnFocusRef}
    >
      {addMode ? (
        <>
          <PersonPickerBody
            mode="select"
            excludeUserIds={activeParticipants.map((participant) => participant.user_id)}
            selectedUserIds={selectedIds}
            onToggleSelect={toggleSelect}
          />
          <div className="new-group-submit">
            <Button
              fullWidth
              disabled={selectedIds.length === 0}
              loading={addingParticipants}
              onClick={() => void confirmAdd()}
            >
              Ekle ({selectedIds.length})
            </Button>
          </div>
        </>
      ) : (
        <>
          {canManage && (
            <Button variant="secondary" leadingIcon={<UserPlus />} onClick={() => setAddMode(true)}>
              Üye ekle
            </Button>
          )}
          <ul className="group-participant-list" aria-label="Grup üyeleri">
            {activeParticipants.map((participant) => {
              const isSelf = participant.user_id === currentUserId;
              return (
                <li key={participant.user_id} className="group-participant-row">
                  <span className="person-avatar" aria-hidden="true">
                    {participant.username.slice(0, 2).toLocaleUpperCase("tr-TR")}
                  </span>
                  <span className="person-row-content">
                    <strong>{participant.username}</strong>
                    {participant.role_in_conversation === "owner" && (
                      <span className="person-row-meta">
                        <Crown size={13} /> Grup sahibi
                      </span>
                    )}
                  </span>
                  {isSelf ? (
                    <IconButton
                      icon={<LogOut />}
                      variant="ghost"
                      className="danger-text"
                      aria-label="Gruptan ayrıl"
                      onClick={() => void onLeave()}
                    />
                  ) : canManage ? (
                    <IconButton
                      icon={<UserMinus />}
                      variant="ghost"
                      className="danger-text"
                      aria-label={`${participant.username} kullanıcısını gruptan çıkar`}
                      loading={removingParticipantId === participant.user_id}
                      onClick={() => void onRemoveParticipant(participant.user_id)}
                    />
                  ) : null}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </Drawer>
  );
}
