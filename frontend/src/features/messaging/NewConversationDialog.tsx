import { useState } from "react";
import { Button } from "../../components/Button";
import { Input } from "../../components/FormControls";
import { Dialog } from "../../components/Overlay";
import { PersonPickerBody } from "./PersonPickerBody";

export function NewConversationDialog({
  open,
  onClose,
  onOpenDm,
  openingDmUserId,
  onCreateGroup,
  creatingGroup,
}: {
  open: boolean;
  onClose: () => void;
  onOpenDm: (userId: string) => void;
  openingDmUserId: string | null;
  onCreateGroup: (title: string, participantIds: string[]) => Promise<void>;
  creatingGroup: boolean;
}) {
  const [tab, setTab] = useState<"dm" | "group">("dm");
  const [title, setTitle] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  const close = () => {
    onClose();
    setTab("dm");
    setTitle("");
    setSelectedIds([]);
  };

  const toggleSelect = (userId: string) => {
    setSelectedIds((current) =>
      current.includes(userId) ? current.filter((id) => id !== userId) : [...current, userId],
    );
  };

  const submitGroup = async () => {
    if (!title.trim() || selectedIds.length === 0) return;
    await onCreateGroup(title.trim(), selectedIds);
    close();
  };

  return (
    <Dialog open={open} title="Yeni konuşma" onClose={close}>
      <div className="new-conversation-tabs" role="tablist" aria-label="Konuşma türü">
        <Button
          role="tab"
          aria-selected={tab === "dm"}
          variant={tab === "dm" ? "primary" : "outline"}
          size="sm"
          onClick={() => setTab("dm")}
        >
          Birebir
        </Button>
        <Button
          role="tab"
          aria-selected={tab === "group"}
          variant={tab === "group" ? "primary" : "outline"}
          size="sm"
          onClick={() => setTab("group")}
        >
          Grup
        </Button>
      </div>

      {tab === "dm" ? (
        <PersonPickerBody
          mode="message"
          onMessage={(userId) => {
            onOpenDm(userId);
            close();
          }}
          messagingUserId={openingDmUserId}
        />
      ) : (
        <div className="new-group-form">
          <Input
            label="Grup adı"
            value={title}
            maxLength={200}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Örn. Proje Ekibi"
          />
          <PersonPickerBody
            mode="select"
            selectedUserIds={selectedIds}
            onToggleSelect={toggleSelect}
          />
          <div className="new-group-submit">
            <Button
              fullWidth
              disabled={!title.trim() || selectedIds.length === 0}
              loading={creatingGroup}
              onClick={() => void submitGroup()}
            >
              Grup oluştur ({selectedIds.length} üye)
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
