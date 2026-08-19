import { ArrowRight, FilePenLine, FilePlus2, FileText, Search, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { DocumentMetadata } from "../../types/documents";
import type { PersistedDraft } from "../../types/drafts";
import { Button, IconButton } from "../../components/Button";
import { Input } from "../../components/FormControls";
import { ListRow } from "../../components/ListRow";
import { OverlayBackdrop } from "../../components/Surface";

export function DocumentSelector({
  documents,
  drafts = [],
  selected,
  selectedDraft = null,
  onSelect,
  onSelectDraft,
  onClear,
  onClearDraft,
}: {
  documents: DocumentMetadata[];
  drafts?: PersistedDraft[];
  selected: DocumentMetadata | null;
  selectedDraft?: PersistedDraft | null;
  onSelect: (document: DocumentMetadata) => void;
  onSelectDraft?: (draft: PersistedDraft) => void;
  onClear: () => void;
  onClearDraft?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"document" | "draft">(
    selectedDraft ? "draft" : "document",
  );
  const [query, setQuery] = useState("");
  const triggerRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const filteredDocuments = useMemo(
    () => documents.filter((document) =>
      `${document.file_name} ${document.document_type_label}`
        .toLocaleLowerCase("tr-TR")
        .includes(query.toLocaleLowerCase("tr-TR")),
    ),
    [documents, query],
  );
  const filteredDrafts = useMemo(
    () => drafts.filter((draft) => {
      const subject = draft.content.match(/^[ \t]*Konu[ \t]*:[ \t]*(.+)$/im)?.[1]?.trim() ?? "";
      return `${subject} ${draft.correspondence_type ?? ""} ${draft.destination ?? ""}`
        .toLocaleLowerCase("tr-TR")
        .includes(query.toLocaleLowerCase("tr-TR"));
    }),
    [drafts, query],
  );
  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    window.setTimeout(() => triggerRef.current?.focus(), 0);
  }, []);
  useEffect(() => {
    if (!open) return;
    searchRef.current?.focus();
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [close, open]);

  return (
    <div className="document-selector">
      {selected ? (
        <div className="selected-document">
          <FileText size={16} />
          <span className="selected-document-copy">
            <small className="selected-document-label">Seçili evrak</small>
            <strong className="selected-document-title" title={selected.file_name}>
              {selected.file_name}
            </strong>
          </span>
          <IconButton
            icon={<X />}
            onClick={onClear}
            aria-label="Evrak seçimini kaldır"
          />
        </div>
      ) : selectedDraft ? (
        <div className="selected-document selected-draft">
          <FilePenLine size={16} />
          <span className="selected-document-copy">
            <small className="selected-document-label">Revize edilecek taslak</small>
            <strong className="selected-document-title" title={selectedDraft.content}>
              {selectedDraft.content.match(/^[ \t]*Konu[ \t]*:[ \t]*(.+)$/im)?.[1]?.trim()
                || selectedDraft.correspondence_type?.replace(/_/g, " ")
                || "Resmî taslak"}
            </strong>
          </span>
          <IconButton
            icon={<X />}
            onClick={onClearDraft}
            aria-label="Taslak seçimini kaldır"
          />
        </div>
      ) : (
        <Button
          ref={triggerRef}
          variant="outline"
          size="sm"
          className="attach-document-button"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => { setTab("document"); setOpen(true); }}
          leadingIcon={<FilePlus2 />}
        >
          Evrak veya taslak ekle
        </Button>
      )}
      {open && (
        <div className="document-picker-layer">
          <OverlayBackdrop className="document-picker-backdrop" aria-label="Bağlam seçiciyi kapat" onClick={close} />
          <section className="document-picker" role="dialog" aria-modal="true" aria-labelledby="document-picker-title">
            <header>
              <div><h2 id="document-picker-title">Sohbet bağlamı seç</h2><p>Bir evrak üzerinde çalışın veya kayıtlı bir taslağı revize edin.</p></div>
              <IconButton icon={<X />} aria-label="Bağlam seçiciyi kapat" onClick={close} />
            </header>
            <div className="document-picker-tabs" role="tablist" aria-label="Bağlam türü">
              <button type="button" role="tab" aria-selected={tab === "document"} onClick={() => { setTab("document"); setQuery(""); }}>Evraklar</button>
              <button type="button" role="tab" aria-selected={tab === "draft"} onClick={() => { setTab("draft"); setQuery(""); }}>Taslaklar</button>
            </div>
            <Input ref={searchRef} fieldClassName="document-picker-search" leadingIcon={<Search />} aria-label={tab === "document" ? "Evraklarda ara" : "Taslaklarda ara"} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={tab === "document" ? "Evraklarda ara" : "Taslaklarda ara"} />
            <div className="document-picker-list">
              {tab === "document" && filteredDocuments.length === 0 ? (
                <div className="document-picker-empty">
                  <FileText size={22} />
                  <p>{documents.length === 0 ? "Henüz yüklenmiş evrak yok." : "Aramanızla eşleşen evrak bulunamadı."}</p>
                </div>
              ) : tab === "document" ? filteredDocuments.map((document) => (
                <ListRow
                  type="button"
                  key={document.storage_path}
                  onClick={() => { onSelect(document); close(); }}
                  leading={<FileText />}
                  primary={document.file_name}
                  secondary={document.document_type_label || "Evrak"}
                />
              )) : filteredDrafts.length === 0 ? (
                <div className="document-picker-empty">
                  <FilePenLine size={22} />
                  <p>{drafts.length === 0 ? "Henüz kayıtlı taslak yok." : "Aramanızla eşleşen taslak bulunamadı."}</p>
                </div>
              ) : filteredDrafts.map((draft) => {
                const subject = draft.content.match(/^[ \t]*Konu[ \t]*:[ \t]*(.+)$/im)?.[1]?.trim();
                return (
                  <ListRow
                    type="button"
                    key={draft.id}
                    onClick={() => { onSelectDraft?.(draft); close(); }}
                    leading={<FilePenLine />}
                    primary={subject || draft.correspondence_type?.replace(/_/g, " ") || "Resmî taslak"}
                    secondary={`v${draft.version} · ${draft.destination || "Hedef belirtilmedi"}`}
                  />
                );
              })}
            </div>
            <footer>
              <Link to={tab === "document" ? "/documents" : "/drafts"} onClick={close}>
                {tab === "document" ? "Evrakları yönet veya yeni evrak yükle" : "Tüm taslakları aç"} <ArrowRight size={15} />
              </Link>
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}
