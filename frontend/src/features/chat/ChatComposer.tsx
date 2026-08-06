import { Send } from "lucide-react";
import { useState, type FormEvent, type KeyboardEvent } from "react";
import { DocumentSelector } from "../documents/DocumentSelector";
import type { DocumentMetadata, ReasoningLevel } from "../../types/documents";

export function ChatComposer({
  documents,
  selectedDocument,
  loading,
  onSelectDocument,
  onClearDocument,
  onSend,
}: {
  documents: DocumentMetadata[];
  selectedDocument: DocumentMetadata | null;
  loading: boolean;
  onSelectDocument: (document: DocumentMetadata) => void;
  onClearDocument: () => void;
  onSend: (
    text: string,
    level: ReasoningLevel,
    useDocument: boolean,
  ) => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [level, setLevel] = useState<ReasoningLevel>("balanced");
  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!text.trim() || loading) return;
    const value = text;
    setText("");
    await onSend(value, level, Boolean(selectedDocument));
  };
  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  };
  return (
    <form className="chat-composer" onSubmit={(event) => void submit(event)}>
      <div className="composer-controls">
        <DocumentSelector
          documents={documents}
          selected={selectedDocument}
          onSelect={onSelectDocument}
          onClear={onClearDocument}
        />
        <label className="compact-select">
          <span>Yanıt biçimi</span>
          <select
            value={level}
            onChange={(event) => setLevel(event.target.value as ReasoningLevel)}
          >
            <option value="fast">Hızlı</option>
            <option value="balanced">Dengeli</option>
            <option value="deep">Derin</option>
          </select>
        </label>
      </div>
      <div className="composer-input">
        <textarea
          value={text}
          disabled={loading}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={keyDown}
          maxLength={8000}
          rows={1}
          placeholder={
            loading
              ? "Bekleyen işlem tamamlandığında yeniden yazabilirsiniz."
              : "Bir soru yazın veya resmî yazı hazırlanmasını isteyin…"
          }
          aria-label="Sohbet mesajı"
        />
        <button
          className="send-button"
          type="submit"
          disabled={loading || !text.trim()}
          aria-label="Mesajı gönder"
        >
          <Send size={18} />
        </button>
      </div>
      <small>Göndermek için Enter, yeni satır için Shift + Enter</small>
    </form>
  );
}
