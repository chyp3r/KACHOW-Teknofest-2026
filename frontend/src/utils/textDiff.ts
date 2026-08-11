export interface DiffSegment {
  text: string;
  changed: boolean;
}

function tokenize(text: string): string[] {
  return text.split(/(\s+)/).filter((token) => token.length > 0);
}

// Word-level diff (LCS over whitespace-preserving tokens), collapsed into
// runs of unchanged/changed text. Used to animate exactly what a post-draft
// guardrail pass changed (e.g. a redacted phone number) in place, instead of
// the whole streamed draft silently vanishing and reappearing edited.
//
// Always covers `next` in full -- callers render this instead of `next`
// directly, never alongside it.
export function diffWords(previous: string, next: string): DiffSegment[] {
  if (!previous) return next ? [{ text: next, changed: false }] : [];

  const a = tokenize(previous);
  const b = tokenize(next);
  const n = a.length;
  const m = b.length;
  if (m === 0) return [];

  const lengths: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lengths[i][j] =
        a[i] === b[j] ? lengths[i + 1][j + 1] + 1 : Math.max(lengths[i + 1][j], lengths[i][j + 1]);
    }
  }

  const segments: DiffSegment[] = [];
  const push = (text: string, changed: boolean) => {
    if (!text) return;
    const last = segments[segments.length - 1];
    if (last && last.changed === changed) last.text += text;
    else segments.push({ text, changed });
  };

  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      push(b[j], false);
      i += 1;
      j += 1;
    } else if (lengths[i + 1][j] >= lengths[i][j + 1]) {
      i += 1; // token dropped from the streamed preview; contributes nothing to `next`
    } else {
      push(b[j], true);
      j += 1;
    }
  }
  while (j < m) {
    push(b[j], true);
    j += 1;
  }

  return segments;
}

// Whether the changed portion is small enough to animate as a targeted
// highlight rather than a wholesale rewrite -- past this ratio, marking
// "almost everything" changed reads as broken, not helpful, and the caller
// should fall back to showing the final text plainly.
export function isTargetedDiff(segments: DiffSegment[], threshold = 0.4): boolean {
  const total = segments.reduce((sum, segment) => sum + segment.text.length, 0);
  if (total === 0) return true;
  const changed = segments
    .filter((segment) => segment.changed)
    .reduce((sum, segment) => sum + segment.text.length, 0);
  return changed / total <= threshold;
}
