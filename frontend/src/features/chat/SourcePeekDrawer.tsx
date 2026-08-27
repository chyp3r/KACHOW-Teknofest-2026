import { useEffect, useRef } from "react";
import { FileText } from "lucide-react";
import { Drawer } from "../../components/Overlay";
import { EmptyState } from "../../components/EmptyState";
import { Spinner } from "../../components/Surface";
import { findSourceExcerpt, type SourceExcerpt } from "./sourceExcerpt";
import type { CitationTarget } from "./MarkdownMessage";

export type { CitationTarget };

/**
 * Locate the cited quote inside the page.
 *
 * Exact first: the model quotes the document verbatim, so a plain substring
 * search normally lands it -- and unlike the fuzzy pass it cannot land on the
 * wrong sentence. The fuzzy matcher stays as a fallback for a quote the model
 * lightly reflowed (collapsed whitespace, trimmed a clause).
 */
function locate(pageText: string, quote: string): SourceExcerpt | null {
  if (!pageText || !quote) return null;

  const exact = pageText.indexOf(quote);
  if (exact !== -1) {
    return {
      before: pageText.slice(0, exact),
      match: pageText.slice(exact, exact + quote.length),
      after: pageText.slice(exact + quote.length),
    };
  }
  return findSourceExcerpt(pageText, quote);
}

/**
 * The source behind a citation: the quoted sentence, and -- when the page is
 * known and the quote can be placed in it -- the whole page with that sentence
 * highlighted, so a reader checking the claim sees what surrounds it.
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
  const pageText =
    target?.page && pages ? (pages[target.page - 1] ?? "") : "";
  const excerpt = target ? locate(pageText, target.quote) : null;

  useEffect(() => {
    // Center the highlight rather than leaving it wherever the page happens to
    // start -- the point of opening this is to land on the claim. Called
    // defensively: scrollIntoView is absent in jsdom and is a progressive
    // enhancement anyway, so its absence must not take the drawer down with it.
    markRef.current?.scrollIntoView?.({ block: "center" });
  }, [target, excerpt]);

  const heading = target
    ? target.index
      ? `Kaynak ${target.index}${target.page ? ` — Sayfa ${target.page}` : ""}`
      : `Kaynak${target.page ? ` — Sayfa ${target.page}` : ""}`
    : "Kaynak";

  return (
    <Drawer
      open={target !== null}
      id="source-peek-drawer"
      className="source-peek-drawer"
      title={heading}
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

      {/* The model's own quote, shown first: it is the answer to "where did
          this come from", and it is present even when the page text is not. */}
      {target?.quote && (
        <blockquote className="source-peek-quote">{target.quote}</blockquote>
      )}

      {loading ? (
        <div className="processing-line">
          <Spinner label="Belge metni yükleniyor" />
          Belge metni yükleniyor…
        </div>
      ) : !pageText ? (
        !target?.quote && (
          <EmptyState
            icon={FileText}
            title="Kaynak metni bulunamadı"
            description="Bu atıf için evrakta bir kaynak metni bulunamadı."
          />
        )
      ) : (
        <>
          {!excerpt && (
            <p className="source-peek-note">
              Alıntı sayfada birebir bulunamadı; sayfanın tamamı aşağıda.
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
