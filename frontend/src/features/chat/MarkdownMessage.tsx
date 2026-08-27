import { Children, isValidElement, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";

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

/** Replace every `[s. N]` inside a plain-text node with a citation badge. */
function withCitationBadges(text: string, keyPrefix: string): ReactNode[] {
  const parts: ReactNode[] = [];
  let cursor = 0;
  let index = 0;

  // `matchAll` needs the /g flag, which makes the regex stateful; a fresh
  // iterator per call keeps concurrent renders from sharing lastIndex.
  for (const match of text.matchAll(CITATION_PATTERN)) {
    const start = match.index ?? 0;
    if (start > cursor) parts.push(text.slice(cursor, start));
    parts.push(
      <span className="page-citation" key={`${keyPrefix}-${index}`}>
        Sayfa {match[1]}
      </span>,
    );
    cursor = start + match[0].length;
    index += 1;
  }

  if (index === 0) return [text];
  if (cursor < text.length) parts.push(text.slice(cursor));
  return parts;
}

/** Walk a node tree, badging citations in every string leaf. */
function badgeCitations(children: ReactNode, keyPrefix = "cite"): ReactNode {
  return Children.map(children, (child, childIndex) => {
    if (typeof child === "string") {
      return withCitationBadges(child, `${keyPrefix}-${childIndex}`);
    }
    // Recurse through inline formatting (**bold**, *italic*, links) so a
    // citation inside one is still caught. Elements whose children live
    // somewhere other than props.children are left untouched.
    if (isValidElement<{ children?: ReactNode }>(child) && child.props.children) {
      return {
        ...child,
        props: {
          ...child.props,
          children: badgeCitations(child.props.children, `${keyPrefix}-${childIndex}`),
        },
      };
    }
    return child;
  });
}

/** Element types that can carry prose, and therefore a citation. */
const COMPONENTS: Components = {
  p: ({ children }) => <p>{badgeCitations(children)}</p>,
  li: ({ children }) => <li>{badgeCitations(children)}</li>,
  td: ({ children }) => <td>{badgeCitations(children)}</td>,
  blockquote: ({ children }) => <blockquote>{badgeCitations(children)}</blockquote>,
};

/**
 * The assistant's markdown, with page citations rendered as badges.
 *
 * A drop-in replacement for a bare `<ReactMarkdown>` in the chat surfaces --
 * see `AnimatedMessageText` and `MessageList`'s streaming preview.
 */
export function MarkdownMessage({ text }: { text: string }) {
  return <ReactMarkdown components={COMPONENTS}>{text}</ReactMarkdown>;
}
