import { Mic, MicOff, Send } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { DocumentSelector } from "../documents/DocumentSelector";
import type { DocumentMetadata, ReasoningLevel } from "../../types/documents";
import type { PersistedDraft } from "../../types/drafts";
import { IconButton } from "../../components/Button";
import { Select, Textarea } from "../../components/FormControls";
import { useSpeechToText } from "../../hooks/useSpeechToText";

export function ChatComposer({
  documents,
  drafts,
  selectedDocument,
  selectedDraft,
  loading,
  onSelectDocument,
  onSelectDraft,
  onClearDocument,
  onClearDraft,
  onSend,
  promptTemplate,
  onPromptTemplateConsumed,
}: {
  documents: DocumentMetadata[];
  drafts: PersistedDraft[];
  selectedDocument: DocumentMetadata | null;
  selectedDraft: PersistedDraft | null;
  loading: boolean;
  onSelectDocument: (document: DocumentMetadata) => void;
  onSelectDraft: (draft: PersistedDraft) => void;
  onClearDocument: () => void;
  onClearDraft: () => void;
  onSend: (
    text: string,
    level: ReasoningLevel,
    useDocument: boolean,
  ) => Promise<void>;
  promptTemplate?: string | null;
  onPromptTemplateConsumed?: () => void;
}) {
  const [text, setText] = useState("");
  const [level, setLevel] = useState<ReasoningLevel>("balanced");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dictationBaseRef = useRef("");
  const handleTranscript = useCallback((transcript: string, isFinal: boolean) => {
    setText(() => {
      const base = dictationBaseRef.current;
      const needsSpace = base.length > 0 && !/[\s\n]$/.test(base);
      const next = `${base}${needsSpace ? " " : ""}${transcript}`;
      if (isFinal) dictationBaseRef.current = next;
      return next;
    });
  }, []);
  const {
    supported: speechSupported,
    listening: speechListening,
    error: speechError,
    toggle: toggleSpeech,
  } = useSpeechToText({ lang: "tr-TR", onTranscript: handleTranscript });
  const handleMicClick = () => {
    if (!speechListening) {
      dictationBaseRef.current = text;
    }
    toggleSpeech();
  };
  useEffect(() => {
    if (!promptTemplate) return;
    setText(promptTemplate);
    onPromptTemplateConsumed?.();
    textareaRef.current?.focus();
  }, [onPromptTemplateConsumed, promptTemplate]);
  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!text.trim() || loading) return;
    const value = text;
    setText("");
    dictationBaseRef.current = "";
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
          drafts={drafts}
          selected={selectedDocument}
          selectedDraft={selectedDraft}
          onSelect={onSelectDocument}
          onSelectDraft={onSelectDraft}
          onClear={onClearDocument}
          onClearDraft={onClearDraft}
        />
        <label className="composer-mode">
          <span>Çalışma modu</span>
          <Select
            controlSize="sm"
            value={level}
            onChange={(event) => setLevel(event.target.value as ReasoningLevel)}
          >
            <option value="fast">Hızlı</option>
            <option value="balanced">Dengeli</option>
            <option value="deep">Derinlemesine</option>
          </Select>
        </label>
      </div>
      <div className="composer-input">
        <Textarea
          ref={textareaRef}
          value={text}
          disabled={loading}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={keyDown}
          maxLength={8000}
          rows={1}
          placeholder={
            loading
              ? "Bekleyen işlem tamamlandığında yeniden yazabilirsiniz."
              : selectedDraft
                ? "Seçili taslak için revizyon talimatınızı yazın…"
                : "Bir soru yazın veya resmî yazı hazırlanmasını isteyin…"
          }
          aria-label="Sohbet mesajı"
          aria-describedby="composer-keyboard-help"
        />
        <div className="composer-actions">
          {speechSupported ? (
            <IconButton
              className={`mic-button${speechListening ? " is-listening" : ""}`}
              type="button"
              variant={speechListening ? "primary" : "outline"}
              icon={speechListening ? <MicOff /> : <Mic />}
              disabled={loading}
              onClick={handleMicClick}
              tooltip={speechListening ? "Dikteyi durdur" : "Sesle yazdır"}
              aria-label={speechListening ? "Dikteyi durdur" : "Sesle yazdır"}
            />
          ) : null}
          <IconButton
            className="send-button"
            type="submit"
            variant="primary"
            icon={<Send />}
            loading={loading}
            disabled={loading || !text.trim()}
            aria-label={loading ? "Mesaj gönderiliyor" : "Mesajı gönder"}
          />
        </div>
      </div>
      <small className="composer-keyboard-help" id="composer-keyboard-help">
        {speechError
          ? speechError
          : speechListening
            ? "Dinleniyor… durdurmak için mikrofon simgesine tekrar basın."
            : "Göndermek için Enter, yeni satır için Shift + Enter"}
      </small>
    </form>
  );
}
