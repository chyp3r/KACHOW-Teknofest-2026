import { Children, isValidElement, useMemo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import { parseReplyCitations, type Citation } from "./citations";

/**
 * A numbered citation marker in the prose: `[1]`, `[2]`.
 *
 * Only badged when the reply's sources block actually defines that number --
 * without which "Madde [5]" or a stray bracketed figure would be dressed up as
 * a source the reader could click into and find nothing behind.
 */
const MARKER_PATTERN = /\[(\d+)\]/g;

/**
 * The legacy page-only anchor (`[s. 3]`, app/ai/documents/anchors.py). Still
 * rendered so an older reply in the history, or a model turn that reaches for
 * the old form, degrades to a readable label rather than raw punctuation.
 */
const PAGE_ANCHOR_PATTERN = /\[s\.\s*(\d+)\]/g;

/** What a citation badge hands over when the reader clicks it. */
export interface CitationTarget {
  /** Page the quote came from, when the model reported one. */
  page?: number;
  /** The source sentence, quoted from the document by the model. */
  quote: string;
  /** The marker number, for the drawer's own heading. */
  index?: number;
}

/** Replace citation markers in a plain-text node with badges. */
function withCitationBadges(
  text: string,
  keyPrefix: string,
  citations: Map<number, Citation>,
  onCitationClick?: (target: CitationTarget) => void,
): ReactNode[] {
  const parts: ReactNode[] = [];
  let cursor = 0;
  let matched = 0;

  // Page anchors are matched first and consume their span, so the `[s. 3]` in
  // a legacy reply is never also read as the number-marker `[3]`.
  const spans = [
    ...[...text.matchAll(PAGE_ANCHOR_PATTERN)].map((match) => ({
      start: match.index ?? 0,
      length: match[0].length,
      label: `Sayfa ${match[1]}`,
      target: { page: Number(match[1]), quote: "" } satisfies CitationTarget,
    })),
    ...[...text.matchAll(MARKER_PATTERN)].flatMap((match) => {
      const citation = citations.get(Number(match[1]));
      if (!citation) return [];
      return [
        {
          start: match.index ?? 0,
          length: match[0].length,
          label: String(citation.index),
          target: {
            page: citation.page,
            quote: citation.quote,
            index: citation.index,
          } satisfies CitationTarget,
        },
      ];
    }),
  ]
    .sort((left, right) => left.start - right.start)
    .filter((span, index, all) => index === 0 || span.start >= all[index - 1].start + all[index - 1].length);

  for (const span of spans) {
    if (span.start > cursor) parts.push(text.slice(cursor, span.start));

    const key = `${keyPrefix}-${matched}`;
    const title = span.target.quote
      ? `Kaynağı göster: ${span.target.quote}`
      : `${span.label} — kaynağı göster`;
    parts.push(
      onCitationClick ? (
        <button
          type="button"
          className="page-citation page-citation-button"
          key={key}
          onClick={() => onCitationClick(span.target)}
          title={title}
          aria-label={`Kaynak ${span.label}. Bu bilginin evraktaki kaynağını göster.`}
        >
          {span.label}
        </button>
      ) : (
        <span className="page-citation" key={key}>
          {span.label}
        </span>
      ),
    );
    cursor = span.start + span.length;
    matched += 1;
  }

  if (matched === 0) return [text];
  if (cursor < text.length) parts.push(text.slice(cursor));
  return parts;
}

/** Walk a node tree, badging citations in every string leaf. */
function badgeCitations(
  children: ReactNode,
  citations: Map<number, Citation>,
  onCitationClick?: (target: CitationTarget) => void,
  keyPrefix = "cite",
): ReactNode {
  return Children.map(children, (child, childIndex) => {
    if (typeof child === "string") {
      return withCitationBadges(child, `${keyPrefix}-${childIndex}`, citations, onCitationClick);
    }
    // Recurse through inline formatting (**bold**, *italic*, links) so a
    // citation inside one is still caught. Elements whose children live
    // somewhere other than props.children are left untouched.
    if (isValidElement<{ children?: ReactNode }>(child) && child.props.children) {
      return {
        ...child,
        props: {
          ...child.props,
          children: badgeCitations(
            child.props.children,
            citations,
            onCitationClick,
            `${keyPrefix}-${childIndex}`,
          ),
        },
      };
    }
    return child;
  });
}

/** Element types that can carry prose, and therefore a citation. */
function buildComponents(
  citations: Map<number, Citation>,
  onCitationClick?: (target: CitationTarget) => void,
): Components {
  const badge = (children: ReactNode) => badgeCitations(children, citations, onCitationClick);
  return {
    p: ({ children }) => <p>{badge(children)}</p>,
    li: ({ children }) => <li>{badge(children)}</li>,
    td: ({ children }) => <td>{badge(children)}</td>,
    blockquote: ({ children }) => <blockquote>{badge(children)}</blockquote>,
  };
}

/**
 * The assistant's markdown, with its sources block parsed out and its citation
 * markers rendered as badges.
 *
 * A drop-in replacement for a bare `<ReactMarkdown>` in the chat surfaces --
 * see `AnimatedMessageText` and `MessageList`'s streaming preview. Passing
 * `onCitationClick` turns each badge into a button that opens the source;
 * without it they stay as plain, non-interactive labels.
 */
export function MarkdownMessage({
  text,
  onCitationClick,
}: {
  text: string;
  onCitationClick?: (target: CitationTarget) => void;
}) {
  const { body, citations } = useMemo(() => parseReplyCitations(text), [text]);
  const components = useMemo(
    () => buildComponents(citations, onCitationClick),
    [citations, onCitationClick],
  );

  // Every source, listed once at the end. Showing only the ones the model
  // forgot to reference inline read as arbitrary -- an answer with `1` beside
  // a sentence and a bare "KAYNAKLAR 2 3" underneath looks like the last two
  // belong to something else. A complete list is a bibliography; a partial
  // one is a puzzle.
  const sources = useMemo(
    () => [...citations.values()].sort((left, right) => left.index - right.index),
    [citations],
  );

  return (
    <>
      <ReactMarkdown components={components}>{body}</ReactMarkdown>
      {sources.length > 0 && (
        <section className="citation-list" aria-label="Kaynaklar">
          <h4 className="citation-list-title">Kaynaklar</h4>
          <ol>
            {sources.map((citation) => {
              const label = String(citation.index);
              const page = citation.page ? `s. ${citation.page}` : null;
              const content = (
                <>
                  <span className="page-citation" aria-hidden="true">
                    {label}
                  </span>
                  {page && <span className="citation-list-page">{page}</span>}
                  <span className="citation-list-quote">{citation.quote}</span>
                </>
              );
              return (
                <li key={citation.index}>
                  {onCitationClick ? (
                    <button
                      type="button"
                      className="citation-list-row citation-list-row-button"
                      onClick={() =>
                        onCitationClick({
                          page: citation.page,
                          quote: citation.quote,
                          index: citation.index,
                        })
                      }
                      aria-label={`Kaynak ${label}${page ? `, ${page}` : ""}. Evraktaki yerini göster.`}
                    >
                      {content}
                    </button>
                  ) : (
                    <span className="citation-list-row">{content}</span>
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      )}
    </>
  );
}
