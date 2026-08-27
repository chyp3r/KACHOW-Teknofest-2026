/**
 * Locating a cited claim inside the page it was cited from.
 *
 * The backend's page anchor (`[s. N]`, see app/ai/documents/anchors.py) carries
 * a page number and nothing else -- no character offset. So to show a reader
 * *where* on that page the answer came from, the claim has to be found in the
 * page text on this side, by matching the assistant's own sentence against it.
 *
 * Deliberately lexical, not semantic: the assistant paraphrases, but the
 * load-bearing tokens it paraphrases *around* -- a name, a number, a date --
 * survive almost every rewording, and those are exactly the tokens a reader
 * wants to land on.
 */

/** A page split into the part before the match, the match, and the part after. */
export interface SourceExcerpt {
  before: string;
  match: string;
  after: string;
}

/**
 * Share of the claim's significant tokens a page sentence must carry before we
 * point at it. Below this, highlighting the wrong sentence is worse than
 * highlighting none -- the reader is handed the whole page instead.
 */
const MIN_OVERLAP = 0.34;

/** Tokens this short are structural ("ve", "bir", "bu"), not evidence. */
const MIN_TOKEN_LENGTH = 3;

/** Sentence boundary: terminator + whitespace, or a line break. */
const SENTENCE_BOUNDARY = /(?<=[.!?:;])\s+|\n+/;

/**
 * Fold text for comparison: Turkish-aware lowercase, punctuation collapsed.
 * Mirrors the backend's own `_fold` (app/ai/verification/draft_verifier.py) in
 * intent -- casing and punctuation must never decide a match.
 */
function fold(text: string): string {
  return (
    text
      .toLocaleLowerCase("tr")
      // Join a number's own separators before punctuation is stripped, or
      // "3.83" would shatter into "3" and "83" and be dropped as too short --
      // losing exactly the token a reader most wants to land on. Applied to
      // both sides, so the two still compare equal.
      .replace(/(?<=\d)[.,](?=\d)/g, "")
      .replace(/[^\p{L}\p{N}]+/gu, " ")
      .trim()
  );
}

function significantTokens(text: string): string[] {
  return fold(text)
    .split(" ")
    .filter((token) => token.length >= MIN_TOKEN_LENGTH);
}

/**
 * Find the sentence in `pageText` that the assistant's `claim` came from.
 *
 * @param pageText Full text of the cited page, as extracted.
 * @param claim The assistant's own sentence carrying the citation.
 * @returns The page split around the best-matching sentence, or `null` when
 *   nothing on the page matches well enough to point at (the caller should
 *   then show the page unhighlighted rather than guess).
 */
export function findSourceExcerpt(
  pageText: string,
  claim: string,
): SourceExcerpt | null {
  const claimTokens = new Set(significantTokens(claim));
  if (claimTokens.size === 0 || !pageText.trim()) return null;

  let bestStart = -1;
  let bestEnd = -1;
  let bestScore = 0;

  // Walk the page sentence by sentence, tracking each one's offset span so the
  // winner can be sliced out of the *original* text -- casing, punctuation and
  // line breaks intact, which is the whole point of showing a source.
  let offset = 0;
  for (const sentence of pageText.split(SENTENCE_BOUNDARY)) {
    const start = pageText.indexOf(sentence, offset);
    if (start === -1) continue;
    const end = start + sentence.length;
    offset = end;

    const tokens = significantTokens(sentence);
    if (tokens.length === 0) continue;

    const hits = tokens.filter((token) => claimTokens.has(token)).length;
    if (hits === 0) continue;

    // F1 over the two directions, because neither alone ranks correctly:
    // precision alone hands the win to any two-word line fully contained in
    // the claim (a bare name heading beat the sentence carrying the actual
    // figures), while recall alone hands it to the longest paragraph.
    const precision = hits / tokens.length;
    const recall = hits / claimTokens.size;
    const score = (2 * precision * recall) / (precision + recall);
    if (score > bestScore) {
      bestScore = score;
      bestStart = start;
      bestEnd = end;
    }
  }

  if (bestStart === -1 || bestScore < MIN_OVERLAP) return null;

  return {
    before: pageText.slice(0, bestStart),
    match: pageText.slice(bestStart, bestEnd),
    after: pageText.slice(bestEnd),
  };
}
