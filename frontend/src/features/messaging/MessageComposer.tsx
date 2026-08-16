import { Send } from "lucide-react";
import { useState, type FormEvent, type KeyboardEvent } from "react";
import { IconButton } from "../../components/Button";
import { Textarea } from "../../components/FormControls";
import { MESSAGE_BODY_MAX_LENGTH } from "../../types/messaging";

export function MessageComposer({
  disabled,
  sending,
  onSend,
}: {
  disabled?: boolean;
  sending: boolean;
  onSend: (body: string) => Promise<void>;
}) {
  const [text, setText] = useState("");

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    const value = text.trim();
    if (!value || sending || disabled) return;
    setText("");
    await onSend(value);
  };

  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  };

  return (
    <form className="message-composer" onSubmit={(event) => void submit(event)}>
      <Textarea
        value={text}
        disabled={disabled || sending}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={keyDown}
        maxLength={MESSAGE_BODY_MAX_LENGTH}
        rows={1}
        placeholder={disabled ? "Bu konuşmadan ayrıldınız." : "Bir mesaj yazın…"}
        aria-label="Mesaj"
      />
      <IconButton
        type="submit"
        variant="primary"
        icon={<Send />}
        loading={sending}
        disabled={disabled || sending || !text.trim()}
        aria-label={sending ? "Mesaj gönderiliyor" : "Mesajı gönder"}
      />
    </form>
  );
}
