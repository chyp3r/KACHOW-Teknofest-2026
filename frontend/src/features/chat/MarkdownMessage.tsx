import { Children, isValidElement, useMemo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import type { CitationTarget } from "./SourcePeekDrawer";

/**
 * The backend's page-citation anchor, produced by `format_anchor`
 * (app/ai/documents/anchors.py) whenever an assistant answer traces a fact
 * back to a page of the attached document. It reaches the client inside the
 * reply's markdown as the literal `[s. 3]`, which reads as noise -- this
 * module turns it into a labelled badge instead.
 *
 * Only the rendering changes: the backend keeps emitting `[s. N]`, and
 * `SessionFocus.last_referenced_anchor` / `ToolResult.citations` keep storing
 * that exact string (nothing anywhere parses it, so the two are free to
 * differ).
 */
const CITATION_PATTERN = /\[s\.\s*(\d+)\]/g;

/** Sentence terminators, used to recover the claim a citation is attached to. */
const SENTENCE_END = /[.!?\n]/;

/**
 * The assistant's own sentence ending at `end` -- the claim this citation
 * backs. `SourcePeekDrawer` matches it against the page to find where on that
 * page the claim came from, so it has to be the prose around the anchor and
 * not the anchor itself.
 */
function claimEndingAt(text: string, end: number): string {
  let cursor = end;
  // Step over the gap between the sentence and its anchor, then over the
  // sentence's own terminator -- otherwise the scan below stops on that
  // terminator immediately and returns an empty claim.
  while (cursor > 0 && /\s/.test(text[cursor - 1])) cursor -= 1;
  if (cursor > 0 && SENTENCE_END.test(text[cursor - 1])) cursor -= 1;

  let start = 0;
  for (let index = cursor - 1; index >= 0; index -= 1) {
    const character = text[index];
    if (!SENTENCE_END.test(character)) continue;
    // A decimal point is not a sentence boundary: without this, "3.83" cuts
    // the claim in half and the half that survives is the one without the
    // number -- the very token the source lookup needs most.
    const isDecimalPoint =
      character === "." &&
      /\d/.test(text[index - 1] ?? "") &&
      /\d/.test(text[index + 1] ?? "");
    if (isDecimalPoint) continue;
    start = index + 1;
    break;
  }

  // Drop any other anchors caught in the span; they are markup, not evidence.
  return text.slice(start, end).replace(CITATION_PATTERN, " ").trim();
}

/** Replace every `[s. N]` inside a plain-text node with a citation badge. */
function withCitationBadges(
  text: string,
  keyPrefix: string,
  onCitationClick?: (target: CitationTarget) => void,
): ReactNode[] {
  const parts: ReactNode[] = [];
  let cursor = 0;
  let index = 0;

  // `matchAll` needs the /g flag, which makes the regex stateful; a fresh
  // iterator per call keeps concurrent renders from sharing lastIndex.
  for (const match of text.matchAll(CITATION_PATTERN)) {
    const start = match.index ?? 0;
    if (start > cursor) parts.push(text.slice(cursor, start));

    const page = Number(match[1]);
    const key = `${keyPrefix}-${index}`;
    const label = `Sayfa ${page}`;
    parts.push(
      onCitationClick ? (
        <button
          type="button"
          className="page-citation page-citation-button"
          key={key}
          onClick={() => onCitationClick({ page, claim: claimEndingAt(text, start) })}
          title={`${label} — kaynağı göster`}
          aria-label={`${label}. Bu bilginin evraktaki kaynağını göster.`}
        >
          {label}
        </button>
      ) : (
        <span className="page-citation" key={key}>
          {label}
        </span>
      ),
    );
    cursor = start + match[0].length;
    index += 1;
  }

  if (index === 0) return [text];
  if (cursor < text.length) parts.push(text.slice(cursor));
  return parts;
}

/** Walk a node tree, badging citations in every string leaf. */
function badgeCitations(
  children: ReactNode,
  onCitationClick?: (target: CitationTarget) => void,
  keyPrefix = "cite",
): ReactNode {
  return Children.map(children, (child, childIndex) => {
    if (typeof child === "string") {
      return withCitationBadges(child, `${keyPrefix}-${childIndex}`, onCitationClick);
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
            onCitationClick,
            `${keyPrefix}-${childIndex}`,
          ),
        },
      };
    }
    return child;
  });
}

/**
 * Element types that can carry prose, and therefore a citation. Built per
 * render of a given handler rather than once at module scope, because the
 * handler has to reach `withCitationBadges` through them.
 */
function buildComponents(
  onCitationClick?: (target: CitationTarget) => void,
): Components {
  const badge = (children: ReactNode) => badgeCitations(children, onCitationClick);
  return {
    p: ({ children }) => <p>{badge(children)}</p>,
    li: ({ children }) => <li>{badge(children)}</li>,
    td: ({ children }) => <td>{badge(children)}</td>,
    blockquote: ({ children }) => <blockquote>{badge(children)}</blockquote>,
  };
}

/**
 * The assistant's markdown, with page citations rendered as badges.
 *
 * A drop-in replacement for a bare `<ReactMarkdown>` in the chat surfaces --
 * see `AnimatedMessageText` and `MessageList`'s streaming preview. Passing
 * `onCitationClick` turns each badge into a button that opens the cited page;
 * without it they stay as plain, non-interactive labels.
 */
export function MarkdownMessage({
  text,
  onCitationClick,
}: {
  text: string;
  onCitationClick?: (target: CitationTarget) => void;
}) {
  const components = useMemo(() => buildComponents(onCitationClick), [onCitationClick]);
  return <ReactMarkdown components={components}>{text}</ReactMarkdown>;
}
