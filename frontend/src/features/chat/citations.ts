/**
 * Numbered source citations in an assistant reply.
 *
 * Replaces the earlier page-only anchor (`[s. N]`). That form carried a page
 * number and nothing else, so showing a reader *where* on the page the claim
 * came from meant fuzzy-matching the model's own paraphrase against the page
 * text -- and a paraphrase in an agglutinative language almost never scores
 * high enough, so the lookup reported "not found" nearly every time.
 *
 * Here the model quotes the source itself. The reply carries numbered markers
 * (`[1]`, `[2]`) in the prose and a sources block at the end:
 *
 *     Not ortalaması 3.83'tür [1].
 *
 *     KAYNAKLAR:
 *     [1] (s. 1) Genel not ortalaması 3.83, sınıf sıralaması 144 öğrenci içinde 2.
 *
 * The block is parsed out and never shown; the markers become badges carrying
 * the quote, so locating the passage is an exact string search rather than a
 * guess.
 */

export interface Citation {
  /** The number as written in the prose: `[1]` -> 1. */
  index: number;
  /** Page the quote came from, when the model reported one. */
  page?: number;
  /** The source sentence, quoted from the document by the model. */
  quote: string;
}

export interface ParsedReply {
  /** The reply with the sources block removed -- what the reader sees. */
  body: string;
  /** Citations by their marker number. Empty when the reply has no block. */
  citations: Map<number, Citation>;
}

/**
 * The header that opens the sources block. Tolerant of the decorations a model
 * reaches for unprompted: a markdown heading, bold, a trailing colon.
 */
const SOURCES_HEADER = /^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*)?[ \t]*KAYNAKLAR[ \t]*(?:\*\*)?[ \t]*:?[ \t]*$/im;

/** One entry: `[1] (s. 1) quoted sentence`, with the page optional. */
const SOURCE_ENTRY = /^[ \t]*[-*]?[ \t]*\[(\d+)\][ \t]*(?:\(?[sS]\.[ \t]*(\d+)\)?)?[ \t]*[:\-–]?[ \t]*(.+?)[ \t]*$/;

/**
 * A half-streamed page marker (`[1] (s. 1`) that the optional page group above
 * gives up on and hands over as the quote instead. Rejected so a badge never
 * briefly claims a page fragment as its source; the next chunk completes the
 * line properly.
 */
const INCOMPLETE_PAGE_MARKER = /^\(?[sS]\.[ \t]*\d*$/;

/**
 * Split a reply into the prose the reader sees and the citations behind it.
 *
 * Tolerant of a partially-streamed reply: the block is stripped from the
 * header onwards, so a half-written sources list is hidden rather than
 * flashing up mid-stream, and simply yields fewer citations until it finishes.
 */
export function parseReplyCitations(text: string): ParsedReply {
  const header = SOURCES_HEADER.exec(text);
  if (!header) return { body: text, citations: new Map() };

  const body = text.slice(0, header.index).trimEnd();
  const citations = new Map<number, Citation>();

  for (const line of text.slice(header.index + header[0].length).split("\n")) {
    const entry = SOURCE_ENTRY.exec(line);
    if (!entry) continue;
    const index = Number(entry[1]);
    const quote = entry[3].replace(/^["“”']|["“”']$/g, "").trim();
    if (!quote || INCOMPLETE_PAGE_MARKER.test(quote)) continue;
    // First definition wins: a model that repeats a number is more likely to
    // be restating than correcting, and the prose above refers to the first.
    if (citations.has(index)) continue;
    citations.set(index, {
      index,
      page: entry[2] ? Number(entry[2]) : undefined,
      quote,
    });
  }

  return { body, citations };
}
