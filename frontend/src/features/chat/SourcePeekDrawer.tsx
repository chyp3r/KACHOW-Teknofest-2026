import { useEffect, useRef } from "react";
import { FileText } from "lucide-react";
import { Drawer } from "../../components/Overlay";
import { EmptyState } from "../../components/EmptyState";
import { Spinner } from "../../components/Surface";
import { findSourceExcerpt } from "./sourceExcerpt";

/** What a citation badge hands over when the reader clicks it. */
export interface CitationTarget {
  /** 1-based page number from the `[s. N]` anchor. */
  page: number;
  /** The assistant's own sentence around the citation, used to locate the claim. */
  claim: string;
}

/**
 * The page a citation points at, with the cited passage highlighted.
 *
 * Shows the *whole* page rather than the matched sentence alone: a reader
 * checking a claim wants to see what surrounds it -- whether the sentence was
 * a heading, a caveat, part of a table. The match is highlighted and scrolled
 * to, so the surrounding context is there without having to be hunted for.
 */
export function SourcePeekDrawer({
  target,
  pages,
  documentName,
  loading = false,
  onClose,
  returnFocusRef,
}: {
  target: CitationTarget | null;
  pages: string[] | null;
  documentName?: string;
  loading?: boolean;
  onClose: () => void;
  returnFocusRef?: React.RefObject<HTMLElement | null>;
}) {
  const markRef = useRef<HTMLElement>(null);
  const pageText = target && pages ? (pages[target.page - 1] ?? "") : "";
  const excerpt = target && pageText ? findSourceExcerpt(pageText, target.claim) : null;

  useEffect(() => {
    // Center the highlight rather than leaving it wherever the page happens to
    // start -- the point of opening this is to land on the claim. Called
    // defensively: scrollIntoView is absent in jsdom and is a progressive
    // enhancement anyway, so its absence must not take the drawer down with it.
    markRef.current?.scrollIntoView?.({ block: "center" });
  }, [target, excerpt]);

  return (
    <Drawer
      open={target !== null}
      id="source-peek-drawer"
      className="source-peek-drawer"
      title={target ? `Kaynak — Sayfa ${target.page}` : "Kaynak"}
      onClose={onClose}
      returnFocusRef={returnFocusRef}
      closeLabel="Kaynak görünümünü kapat"
    >
      {documentName && (
        <p className="source-peek-document">
          <FileText size={14} aria-hidden="true" />
          {documentName}
        </p>
      )}

      {loading ? (
        <div className="processing-line">
          <Spinner label="Belge metni yükleniyor" />
          Belge metni yükleniyor…
        </div>
      ) : !pageText ? (
        <EmptyState
          icon={FileText}
          title="Sayfa metni bulunamadı"
          description="Bu evrakın çıkarılmış metnine şu anda ulaşılamıyor."
        />
      ) : (
        <>
          {!excerpt && (
            <p className="source-peek-note">
              Atfın işaret ettiği tam cümle bu sayfada eşleştirilemedi; sayfanın
              tamamı aşağıda.
            </p>
          )}
          <div className="source-peek-page">
            {excerpt ? (
              <>
                {excerpt.before}
                <mark ref={markRef}>{excerpt.match}</mark>
                {excerpt.after}
              </>
            ) : (
              pageText
            )}
          </div>
        </>
      )}
    </Drawer>
  );
}
