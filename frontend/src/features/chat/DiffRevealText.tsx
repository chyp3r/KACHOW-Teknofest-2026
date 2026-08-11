import type { DiffSegment } from "../../utils/textDiff";

// Renders a message's text with the spans a post-draft pass changed (a
// guardrail redaction, a repair) highlighted with a brief fade -- the
// one-time reveal useChatWorkflow's final_result handler computes against
// what was streamed a moment ago. Plain text, not markdown: the segments
// are word-level slices of the final reply, and re-parsing them through
// ReactMarkdown per-span would fight the diff at word boundaries.
export function DiffRevealText({ segments }: { segments: DiffSegment[] }) {
  return (
    <p className="diff-reveal-text">
      {segments.map((segment, index) =>
        segment.changed ? (
          <mark className="diff-changed" key={index}>
            {segment.text}
          </mark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </p>
  );
}
