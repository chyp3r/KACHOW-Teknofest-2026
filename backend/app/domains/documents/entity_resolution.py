"""Pure entity-resolution pipeline for the knowledge graph's Entity nodes.

`resolve_entities` takes every raw surface-form string a document's
`muhatap` / `gonderen_kurum` / `entities[]` fields produced across the whole
corpus and maps each one to a `ResolvedEntity` -- the canonical node it
belongs to, a human-readable label, a heuristic kind, and every surface form
that was merged into it (so the graph's node inspector can disclose the
merge rather than hide it).

Why this exists at all: the v1 knowledge graph (see `knowledge_graph.py`'s
own docstring) deliberately excluded any node keyed by extracted document
text, because raw string identity puts OCR damage straight into node
identity. Measured on the real corpus, `muhatap` alone carries four surface
forms of one institution -- markdown heading junk, a leaked önerge number, a
clean form, and one with a genuine OCR substitution (Ğ misread as Ç). This
module is what turns "OCR damage in node identity" from a reason to exclude
Kurum/Entity nodes into a reason to *resolve* them instead.

Pipeline, applied to each raw string independently before clustering:

1. Strip leading markdown/list artifacts (`#####`, `*`, `>`, `-`).
2. Strip trailing parentheticals -- `(Kanunlar ve Kararlar Başkanlığı)`.
3. Strip leaked 4+ digit numbers -- an önerge number landing mid-string.
4. Turkish-aware fold to lowercase ASCII, reusing `normalizers._fold` --
   deliberately not a second Turkish case table.
5. Strip urgency markers absorbed into the name as a trailing token --
   `GÜNLÜDÜR` / `İVEDİ` / `ACELE` (measured: `CUMHURBAŞKANI YARDIMCISI
   GÜNLÜDÜR` vs `CUMHURBAŞKANI YARDIMCISI`, same office).
6. Strip a dative/directional case ending from the *final* token only --
   `...BAŞKANLIĞINA` -> `...BAŞKANLIĞI`. Only the two-letter buffer-n
   dative (`-na`/`-ne`) and buffer-y dative (`-ya`/`-ye`) are stripped, not
   a three-letter `-ina`/`-ine` variant: the word already ends in the
   possessive `-ı`/`-i` that the case suffix attaches to, and removing the
   longer variant would eat that possessive vowel too.

What steps 1-6 cannot fix is residual single-character OCR noise (Ğ<->Ç in
the example above folds to two *different* ASCII letters, g and c -- not a
case-folding problem, a genuine misread). That residue is caught by a
deterministic fuzzy pass over the *canonical* keys, not the raw strings:
sort keys, then single-pass agglomeration against already-emitted cluster
representatives via `difflib.SequenceMatcher`, representative = the
lexicographically smallest key in the cluster. Sorting first is what makes
clustering independent of input order -- a plain greedy pass over
unsorted input would make the graph's shape depend on dict/list iteration
order, which is exactly the kind of non-determinism this graph cannot
afford on a projector.
"""

from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional, Sequence

from app.ai.verification.normalizers import _fold

#: Trailing tokens that are urgency/routing markers absorbed into a name
#: field by extraction, not part of the institution's name itself. Already
#: folded (lowercase ASCII) since they are compared against folded tokens.
_URGENCY_MARKERS = {"gunludur", "ivedi", "acele"}

#: The two-letter Turkish dative/directional case endings this corpus's
#: institution names actually carry (buffer-n after a possessive vowel,
#: buffer-y after other vowels). Deliberately excludes the three-letter
#: "-ina"/"-ine" shape -- see the module docstring for why.
_DATIVE_SUFFIXES = ("na", "ne", "ya", "ye")
_MIN_TOKEN_LENGTH_FOR_SUFFIX_STRIP = 6

#: Below this length, two canonical keys are never fuzzy-compared -- short
#: strings produce spuriously high SequenceMatcher ratios (e.g. "tbmm" vs
#: "tbnm" is a single-character diff at 75% length) and risk merging two
#: genuinely different short institutions.
_MIN_FUZZY_LENGTH = 8
_FUZZY_RATIO_THRESHOLD = 0.88

#: Folded tokens that mark an institution regardless of position in the
#: name -- used both to steer the fuzzy-merge-adjacent classifier and to
#: catch multi-word offices the suffix check alone would miss (e.g.
#: "hukuk hizmetleri genel mudurlugu").
_INSTITUTION_TOKENS = {
    "bakanligi", "bakanlik", "baskanligi", "baskanlik", "mudurlugu", "mudurluk",
    "komisyonu", "komisyon", "meclisi", "meclis", "kaymakamligi", "valiligi",
    "genel", "daire", "dairesi", "kurulu", "kurumu", "idaresi", "sayistay",
    "tbmm", "nato", "mnc", "btk", "yerlerine",
}


@dataclass(frozen=True)
class ResolvedEntity:
    """One resolved Entity node: everything the graph builder and the
    frontend's node inspector need."""

    key: str
    label: str
    kind: str  # "kurum" | "kisi" | "diger"
    surface_forms: tuple[str, ...]


def _strip_dative_suffix(token: str) -> str:
    if len(token) < _MIN_TOKEN_LENGTH_FOR_SUFFIX_STRIP:
        return token
    for suffix in _DATIVE_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def _canonicalize_single(raw: Optional[str]) -> Optional[str]:
    """Steps 1-6 of the module docstring's pipeline, applied to one string."""
    if not raw:
        return None
    text = raw.strip()
    text = text.lstrip("#*>- \t")
    # Trailing parenthetical(s), possibly with leading whitespace.
    while "(" in text and text.rstrip().endswith(")"):
        open_index = text.rfind("(")
        if open_index == -1:
            break
        text = text[:open_index].rstrip()
    # Leaked 4+ digit numbers (a document number mid-string).
    text = "".join(
        part if not (part.isdigit() and len(part) >= 4) else " "
        for part in _split_keep_digits(text)
    )
    folded = _fold(text)
    if not folded:
        return None
    tokens = [t for t in folded.split(" ") if t]
    while tokens and tokens[-1] in _URGENCY_MARKERS:
        tokens.pop()
    if not tokens:
        return None
    tokens[-1] = _strip_dative_suffix(tokens[-1])
    canonical = " ".join(t for t in tokens if t)
    return canonical or None


def _split_keep_digits(text: str) -> list[str]:
    """Split into runs of digits and non-digits, e.g. 'a 741393 b' ->
    ['a ', '741393', ' b'] -- lets the caller blank out only the numeric
    runs long enough to be a leaked document/önerge number."""
    parts: list[str] = []
    current = []
    current_is_digit: Optional[bool] = None
    for ch in text:
        is_digit = ch.isdigit()
        if current_is_digit is None or is_digit == current_is_digit:
            current.append(ch)
        else:
            parts.append("".join(current))
            current = [ch]
        current_is_digit = is_digit
    if current:
        parts.append("".join(current))
    return parts


def _cluster_canonical_keys(keys: set[str]) -> dict[str, str]:
    """Map each canonical key to its cluster representative. Deterministic
    and independent of input order: keys are sorted before clustering, and
    the representative of any cluster is always the lexicographically
    smallest key in it (the first-sorted key that started that cluster)."""
    representatives: list[str] = []
    assignment: dict[str, str] = {}
    for key in sorted(keys):
        match = None
        if len(key) >= _MIN_FUZZY_LENGTH:
            for rep in representatives:
                if len(rep) < _MIN_FUZZY_LENGTH:
                    continue
                if SequenceMatcher(None, key, rep).ratio() >= _FUZZY_RATIO_THRESHOLD:
                    match = rep
                    break
        if match is None:
            representatives.append(key)
            assignment[key] = key
        else:
            assignment[key] = match
    return assignment


def _classify_kind(canonical_key: str, label: str) -> str:
    tokens = canonical_key.split(" ")
    if any(t in _INSTITUTION_TOKENS for t in tokens):
        return "kurum"
    if len(tokens) == 1 and len(canonical_key) <= 6:
        # A single short token that survived resolution without matching a
        # known institution word is almost always an abbreviation (NATO,
        # BTK) -- Turkish person names are never a single all-caps token,
        # so treating this as "kisi" would be the more misleading guess.
        letters_only = "".join(ch for ch in label if ch.isalpha())
        if letters_only and letters_only == letters_only.upper():
            return "kurum"
    if len(tokens) > 3:
        return "kurum"
    label_tokens = [t for t in label.split(" ") if t]
    if 1 <= len(label_tokens) <= 3 and all(t[:1].isupper() for t in label_tokens):
        return "kisi"
    return "diger"


def resolve_entities(raw_names: Sequence[Optional[str]]) -> dict[str, "ResolvedEntity"]:
    """Resolve every raw surface-form string into its shared `ResolvedEntity`.

    Args:
        raw_names: Every raw string a document's `muhatap` /
            `gonderen_kurum` / `entities[]` field produced, across every
            document in scope -- duplicates expected and meaningful (they
            drive the "most frequent surface form" label choice).

    Returns:
        A mapping from each *distinct, non-empty* raw string in the input to
        the `ResolvedEntity` its cluster resolved to. Two raw strings that
        merged share an identical `ResolvedEntity` (dataclass equality, not
        just the same `key`). Empty/`None`/whitespace-only entries are
        skipped, not mapped.
    """
    canonical_by_raw: dict[str, str] = {}
    for raw in raw_names:
        if raw is None:
            continue
        canonical = _canonicalize_single(raw)
        if canonical:
            canonical_by_raw[raw] = canonical

    if not canonical_by_raw:
        return {}

    unique_canonical = set(canonical_by_raw.values())
    cluster_of = _cluster_canonical_keys(unique_canonical)

    raw_counts = Counter(raw for raw in raw_names if raw in canonical_by_raw)

    forms_by_representative: dict[str, dict[str, int]] = {}
    for raw, canonical in canonical_by_raw.items():
        representative = cluster_of[canonical]
        forms_by_representative.setdefault(representative, {})[raw] = raw_counts[raw]

    result: dict[str, ResolvedEntity] = {}
    for representative, forms in forms_by_representative.items():
        raw_label = sorted(forms.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        # Measured on the real corpus: a markdown-prefixed surface form can
        # legitimately be the *most frequent* one (5 of 11 occurrences here
        # vs. 4 for the clean form) -- "most frequent wins" would otherwise
        # put "##### TÜRKİYE ... BAŞKANLIĞINA" on a graph node in front of a
        # jury. Only leading markdown noise is stripped for display; a
        # trailing parenthetical is real information (e.g. a sub-office)
        # and survives. `surface_forms` below still discloses the raw,
        # unstripped form -- this is cosmetic only, not a second
        # canonicalization.
        label = raw_label.lstrip("#*>- \t") or raw_label
        surface_forms = tuple(sorted(forms))
        kind = _classify_kind(representative, label)
        entity = ResolvedEntity(key=representative, label=label, kind=kind, surface_forms=surface_forms)
        for raw in forms:
            result[raw] = entity

    return result
