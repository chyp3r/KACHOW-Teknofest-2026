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

  // A reply carrying a sources block is using the numbered form, so a page
  // anchor in its prose is a slip -- the model copying `[s. 3]` out of a tool
  // result. Rendering it as a "Sayfa 3" badge next to plain `1` `2` badges is
  // what made the citations look inconsistent, so it is dropped instead (the
  // page still reaches the reader through the block). A reply with no block is
  // an older one where the anchor is the only citation there is: kept.
  const dropPageAnchors = citations.size > 0;

  // Page anchors are matched first and consume their span, so the `[s. 3]` in
  // a legacy reply is never also read as the number-marker `[3]`.
  const spans = [
    ...[...text.matchAll(PAGE_ANCHOR_PATTERN)].map((match) => {
      const start = match.index ?? 0;
      // Swallow one leading space with the anchor, or dropping it leaves the
      // sentence with a gap before its full stop.
      const spacedStart = start > 0 && text[start - 1] === " " ? start - 1 : start;
      return dropPageAnchors
        ? {
            start: spacedStart,
            length: start + match[0].length - spacedStart,
            label: null,
            target: null,
          }
        : {
            start,
            length: match[0].length,
            label: `Sayfa ${match[1]}`,
            target: { page: Number(match[1]), quote: "" } satisfies CitationTarget,
          };
    }),
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

    // A span with no label is consumed and rendered as nothing -- a stray page
    // anchor in a numbered reply.
    if (span.label === null || span.target === null) {
      cursor = span.start + span.length;
      matched += 1;
      continue;
    }

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
  citationSource,
  onCitationClick,
}: {
  text: string;
  /**
   * The complete reply, when `text` is only the part revealed so far.
   *
   * The sources block sits at the very end, so parsing citations out of a
   * partially-revealed `text` finds none -- and the markers already on screen
   * render as bare `[1]` until the typewriter reaches the end, then snap into
   * badges. Parsing them from the whole reply instead resolves every badge
   * from the first frame.
   */
  citationSource?: string;
  onCitationClick?: (target: CitationTarget) => void;
}) {
  const source = citationSource ?? text;
  const { body: fullBody, citations } = useMemo(
    () => parseReplyCitations(source),
    [source],
  );
  // Only the revealed slice is rendered; `fullBody` above exists to decide
  // which citations the finished answer references.
  const body = useMemo(
    () => (source === text ? fullBody : parseReplyCitations(text).body),
    [source, text, fullBody],
  );
  const components = useMemo(
    () => buildComponents(citations, onCitationClick),
    [citations, onCitationClick],
  );

  // Citations live at the end of the sentence they back, so there is no list
  // under the answer. The one exception is a source the model defined but
  // never referenced: dropping it would make the citation vanish outright --
  // the exact failure that made this feature look broken -- so those trail the
  // answer as a single row of badges. Not a bibliography, just the leftovers.
  // Still revealing: `text` is a prefix of the reply rather than all of it.
  const revealing = source !== text;

  // Measured against the finished answer, not the revealed slice: otherwise a
  // marker the typewriter has not reached yet counts as unreferenced, and its
  // badge appears at the bottom only to vanish once the text catches up.
  //
  // Withheld entirely until the reveal finishes, so the leftovers cannot show
  // up under a half-written answer -- they belong after the text, and arriving
  // first is exactly the out-of-order flash this is meant to avoid.
  const orphans = useMemo(() => {
    if (revealing) return [];
    const referenced = new Set(
      [...fullBody.matchAll(MARKER_PATTERN)].map((match) => Number(match[1])),
    );
    return [...citations.values()]
      .filter((citation) => !referenced.has(citation.index))
      .sort((left, right) => left.index - right.index);
  }, [revealing, fullBody, citations]);

  return (
    <>
      <ReactMarkdown components={components}>{body}</ReactMarkdown>
      {orphans.length > 0 && (
        <p className="citation-trailing">
          {orphans.map((citation) => {
            const label = String(citation.index);
            return onCitationClick ? (
              <button
                type="button"
                className="page-citation page-citation-button"
                key={citation.index}
                onClick={() =>
                  onCitationClick({
                    page: citation.page,
                    quote: citation.quote,
                    index: citation.index,
                  })
                }
                title={`Kaynağı göster: ${citation.quote}`}
                aria-label={`Kaynak ${label}. Bu bilginin evraktaki kaynağını göster.`}
              >
                {label}
              </button>
            ) : (
              <span className="page-citation" key={citation.index}>
                {label}
              </span>
            );
          })}
        </p>
      )}
    </>
  );
}
