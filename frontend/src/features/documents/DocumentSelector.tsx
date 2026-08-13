import { ArrowRight, FilePlus2, FileText, Search, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { DocumentMetadata } from "../../types/documents";
import { Button, IconButton } from "../../components/Button";
import { Input } from "../../components/FormControls";
import { ListRow } from "../../components/ListRow";
import { OverlayBackdrop } from "../../components/Surface";

export function DocumentSelector({
  documents,
  selected,
  onSelect,
  onClear,
}: {
  documents: DocumentMetadata[];
  selected: DocumentMetadata | null;
  onSelect: (document: DocumentMetadata) => void;
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const triggerRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const filtered = useMemo(
    () => documents.filter((document) =>
      `${document.file_name} ${document.document_type_label}`
        .toLocaleLowerCase("tr-TR")
        .includes(query.toLocaleLowerCase("tr-TR")),
    ),
    [documents, query],
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
      ) : (
        <Button
          ref={triggerRef}
          variant="outline"
          size="sm"
          className="attach-document-button"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => setOpen(true)}
          leadingIcon={<FilePlus2 />}
        >
          Evrak ekle
        </Button>
      )}
      {open && (
        <div className="document-picker-layer">
          <OverlayBackdrop className="document-picker-backdrop" aria-label="Evrak seçiciyi kapat" onClick={close} />
          <section className="document-picker" role="dialog" aria-modal="true" aria-labelledby="document-picker-title">
            <header>
              <div><h2 id="document-picker-title">Evrak seç</h2><p>Sohbette kullanmak istediğiniz evrakı seçin.</p></div>
              <IconButton icon={<X />} aria-label="Evrak seçiciyi kapat" onClick={close} />
            </header>
            <Input ref={searchRef} fieldClassName="document-picker-search" leadingIcon={<Search />} aria-label="Evraklarda ara" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Evraklarda ara" />
            <div className="document-picker-list">
              {filtered.length === 0 ? (
                <div className="document-picker-empty">
                  <FileText size={22} />
                  <p>{documents.length === 0 ? "Henüz yüklenmiş evrak yok." : "Aramanızla eşleşen evrak bulunamadı."}</p>
                </div>
              ) : filtered.map((document) => (
                <ListRow
                  type="button"
                  key={document.storage_path}
                  onClick={() => { onSelect(document); close(); }}
                  leading={<FileText />}
                  primary={document.file_name}
                  secondary={document.document_type_label || "Evrak"}
                />
              ))}
            </div>
            <footer>
              <Link to="/documents" onClick={close}>Evrakları yönet veya yeni evrak yükle <ArrowRight size={15} /></Link>
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}
