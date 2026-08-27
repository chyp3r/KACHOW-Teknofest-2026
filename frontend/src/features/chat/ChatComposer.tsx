import { Mic, MicOff, Send } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { DocumentSelector } from "../documents/DocumentSelector";
import { ContextUsageRing } from "./ContextUsageRing";
import type { ContextUsage } from "../../types/chat";
import type { DocumentMetadata, ReasoningLevel } from "../../types/documents";
import type { PersistedDraft } from "../../types/drafts";
import { IconButton } from "../../components/Button";
import { Dropdown, Textarea } from "../../components/FormControls";
import { useSpeechToText } from "../../hooks/useSpeechToText";

export function ChatComposer({
  documents,
  drafts,
  selectedDocument,
  selectedDraft,
  loading,
  compacting = false,
  contextUsage = null,
  onCompact,
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
  compacting?: boolean;
  contextUsage?: ContextUsage | null;
  onCompact?: () => void | Promise<void>;
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
  // The textarea content at the moment dictation started. Fixed for the whole
  // session -- the hook now emits the FULL transcript on every event, so each
  // update is `base + current transcript`, never an append onto the previous
  // result (which double-wrote the final chunk when the mic was stopped).
  const dictationBaseRef = useRef("");
  const handleTranscript = useCallback((transcript: string) => {
    setText(() => {
      const base = dictationBaseRef.current;
      if (!transcript) return base;
      const needsSpace = base.length > 0 && !/[\s\n]$/.test(base);
      return `${base}${needsSpace ? " " : ""}${transcript}`;
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
  const locked = loading || compacting;
  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!text.trim() || locked) return;
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
        <div className="composer-mode-stack">
          <label className="composer-mode">
            <span>Çalışma modu</span>
            <Dropdown
              controlSize="sm"
              placement="top"
              value={level}
              onChange={(event) => setLevel(event.target.value as ReasoningLevel)}
            >
              <option value="fast">Hızlı</option>
              <option value="balanced">Dengeli</option>
              <option value="deep">Derin</option>
            </Dropdown>
          </label>
        </div>
        {contextUsage && (
          <ContextUsageRing
            usage={contextUsage}
            compacting={compacting}
            onCompact={onCompact}
          />
        )}
      </div>
      <div className="composer-input">
        <Textarea
          ref={textareaRef}
          value={text}
          disabled={locked}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={keyDown}
          maxLength={8000}
          rows={1}
          placeholder={
            compacting
              ? "Sohbet sıkıştırılıyor…"
              : loading
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
              disabled={locked}
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
            loading={locked}
            disabled={locked || !text.trim()}
            aria-label={
              compacting
                ? "Sohbet sıkıştırılıyor"
                : loading
                  ? "Mesaj gönderiliyor"
                  : "Mesajı gönder"
            }
          />
        </div>
      </div>
      <small className="composer-keyboard-help" id="composer-keyboard-help">
        {compacting
          ? "Sohbet sıkıştırılıyor; tamamlanınca mesaj alanı yeniden açılır."
          : speechError
            ? speechError
            : speechListening
              ? "Dinleniyor… durdurmak için mikrofon simgesine tekrar basın."
              : "Göndermek için Enter, yeni satır için Shift + Enter"}
      </small>
    </form>
  );
}
