"""Deterministic extraction of the labelled header fields of an official document.

The Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik *specifies*
the header layout: "Sayı:" is a side-heading (m.11), "Tarih:" sits on the same line
at the right margin (m.12), "Konu:" goes one line below (m.13), "İlgi:" lists the
referenced documents (m.15) and "Ek:" follows the signature (m.18). Because the
format is prescribed rather than free-form, these values can be read with regular
expressions at far higher accuracy than a small language model achieves.

How much this matters depends on the model, and both ends were measured on the
12-document sample corpus:

- `qwen3:8b` degrades badly as the schema widens. Asked for a single field it
  returns `sayi` correctly; asked for three at once it returns `sayi` as null and
  can send another field into a repeating-token loop until the generation budget
  is spent. Overall extraction accuracy 28.4% alone, 98.5% with this parser.
- `qwen3.5:9b` (the project default) handles the full schema: 94.0% alone, 97.0%
  with this parser. Here the parser is no longer load-bearing, but it still fixes
  `muhatap` (60% -> 100%), removes two thirds of the wrong values, and cuts
  extraction wall-clock by roughly a third because the model emits fewer fields.

So the parser earns its place on both: as a correctness floor on a small model and
as a precision and latency win on a larger one. Values parsed here take precedence
over model output for the same field.
"""

import re
from typing import Any, Optional

from app.ai.compliance.checker import is_blank, normalize_value
from app.ai.verification.draft_verifier import INSTITUTION_PATTERN, TOKEN_OVERLAP_THRESHOLD

# Every label that can terminate a preceding value on the same line. The
# regulation places "Tarih" to the right of "Sayı" on one line, so a value must
# stop at the next label rather than at the end of the line.
_LABEL_ALTERNATION = (
    r"Sayı|Sayi|Tarih|Konu|İlgi|Ilgi|Ek|Ekler|Dağıtım|Dagitim|"
    r"Gizlilik\s+Derecesi|İvedilik|Ivedilik|Adres|Telefon|E-?posta"
)

#: Matches "Label : value", stopping at end of line or at the next known label.
#: Only spaces and tabs may sit around the colon -- never `\s`, which matches
#: newlines and would let an empty "Konu :" line capture the following line's text.
#: That mattered: it silently invented a value for a field the document leaves blank.
#:
#: `\S{0,3}` before the colon tolerates a short stray token between the label and
#: its colon: real scanned-corpus OCR (see field_recovery calibration against the
#: 45 real CY-*.pdf under datasets/resmi_yazisma/) consistently misreads a form
#: checkbox glyph as "Sayı (o :..." for one recurring template -- this single
#: pattern accounted for the majority of missing `sayi` values across that corpus.
#: Capped at 3 characters so it cannot eat into a genuine value when the format is
#: already a normal "Label : value".
_VALUE_TAIL = (
    rf"[ \t]*\S{{0,3}}[ \t]*[:：][ \t]*(.+?)"
    rf"(?=[ \t]+(?:{_LABEL_ALTERNATION})[ \t]*[:：]|[ \t]*$)"
)

#: A date, either numeric ("16.04.2026") or spelled out ("16 Nisan 2026").
_DATE = (
    r"\d{1,2}[./]\d{1,2}[./]\d{4}"
    r"|\d{1,2}\s+(?:Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)\s+\d{4}"
)
#: RYUEHY m.12 prescribes a "Tarih:" label, but real official correspondence
#: routinely places the date unlabelled at the right of the Sayı line instead
#: (verified against the 45 real scanned CY-*.pdf under datasets/resmi_yazisma/:
#: this was the single largest cause of missing `tarih` in that corpus). Tried
#: only as a fallback when the labelled SINGLE_VALUE_PATTERN entry finds nothing
#: -- see its use in parse_labelled_fields.
_UNLABELLED_DATE_ON_SAYI_LINE = re.compile(
    rf"(?:^|\n)\s*Say[ıi][^\n]*?({_DATE})\s*$", re.MULTILINE
)
#: A second, narrower fallback for the same real-world problem: some vision-
#: model transcriptions break the date onto its own line instead of keeping
#: it glued to the Sayı line (verified against CY-010's glm-ocr:latest header
#: repair: "Sayı : Z-43452547-120.07.03-1841896\n20.04.2026\nKonu : ..." --
#: the labelled and same-line patterns above both find nothing there). Tried
#: only when both of those find nothing, and requires the date to be the
#: *entire* next line -- not merely present somewhere after Sayı -- so a date
#: mentioned later in the body, separated by unrelated content, is never
#: mistaken for the header date.
_UNLABELLED_DATE_ON_LINE_AFTER_SAYI = re.compile(
    rf"(?:^|\n)\s*Say[ıi][^\n]*\n[ \t]*({_DATE})[ \t]*(?:\n|$)", re.MULTILINE
)

SINGLE_VALUE_PATTERN: dict[str, re.Pattern[str]] = {
    "sayi": re.compile(rf"(?:^|\n)\s*Say[ıi]{_VALUE_TAIL}", re.MULTILINE),
    "tarih": re.compile(rf"(?:^|\n|\s)Tarih{_VALUE_TAIL}", re.MULTILINE),
    "konu": re.compile(rf"(?:^|\n)\s*Konu{_VALUE_TAIL}", re.MULTILINE),
    "gizlilik_derecesi": re.compile(
        rf"(?:^|\n)\s*Gizlilik\s+Derecesi{_VALUE_TAIL}", re.MULTILINE | re.IGNORECASE
    ),
    "ivedilik": re.compile(
        rf"(?:^|\n)\s*[İI]vedilik{_VALUE_TAIL}", re.MULTILINE | re.IGNORECASE
    ),
    "adres": re.compile(rf"(?:^|\n)\s*Adres{_VALUE_TAIL}", re.MULTILINE),
}

LIST_VALUE_PATTERN: dict[str, re.Pattern[str]] = {
    "ilgi": re.compile(rf"(?:^|\n)\s*[İI]lgi{_VALUE_TAIL}", re.MULTILINE),
    "ekler": re.compile(rf"(?:^|\n)\s*Ek(?:ler)?{_VALUE_TAIL}", re.MULTILINE),
}

#: Splits an "İlgi:" or "Ek:" value that enumerates several items ("a) ... b) ...").
#: The marker must be followed by whitespace, otherwise the leading "01." of a date
#: like "01.01.2026" is mistaken for an enumerator and the date loses its day.
_LIST_ITEM_SEPARATOR = re.compile(
    r"(?:^|\s)(?:[a-zçğıöşü]\)|\d{1,2}[\.\)])[ \t]+", re.IGNORECASE
)


def _clean(value: str) -> str:
    """Normalise whitespace in a captured value.

    Args:
        value: Raw regex capture.

    Returns:
        The value with collapsed whitespace and no trailing punctuation noise.
    """
    return re.sub(r"\s+", " ", value).strip().strip(",;")


def _split_list(value: str) -> list[str]:
    """Split an enumerated İlgi/Ek value into its items.

    Args:
        value: The raw captured value.

    Returns:
        Cleaned items, or a single-item list when no enumeration is present.
    """
    parts = [part for part in _LIST_ITEM_SEPARATOR.split(value) if part.strip()]
    if len(parts) > 1:
        return [_clean(part) for part in parts]
    cleaned = _clean(value)
    return [cleaned] if cleaned else []


#: Lines that are labelled side-headings rather than free content.
_ANY_LABEL_LINE = re.compile(rf"^\s*(?:{_LABEL_ALTERNATION})[ \t]*[:：]", re.IGNORECASE)
#: "T.C." header line (m.10). Tolerates up to 3 leading non-alphanumeric
#: characters: real OCR (CY-023/027/028/030 in the scanned corpus) consistently
#: glues a decorative border/emblem glyph onto the same line as "T.C."
#: ("* T.C.", ", T.C."), which an exact-match anchor rejected outright, losing
#: the letterhead-institution scan entirely (_parse_sender_institution below
#: never even starts).
_TC_LINE = re.compile(r"^[^A-Za-zÇĞİÖŞÜçğıöşü]{0,3}\s*T\s*\.?\s*C\s*\.?\s*$", re.IGNORECASE)
#: An addressee line: ends in a Turkish dative suffix (m.14), e.g.
#: "ÖRNEK VALİLİĞİNE", "İLGİLİ MAKAMA", "DAĞITIM YERLERİNE".
#:
#: The suffix itself stays upper-case-only, unlike the run before it -- that
#: is what keeps this safe. `.{6,40}?` (any characters, length-capped so it
#: cannot span a whole sentence) tolerates a stray lower-case OCR artefact
#: within an otherwise upper-case addressee line (real OCR on the scanned
#: corpus renders some addressees with an incidental miscased letter or two),
#: while still requiring the line to *end* upper-case, which an ordinary name
#: or lower-case sentence fragment never does. A fully case-insensitive
#: version was tried first and rejected: "Zeynep Kaya" -- an ordinary
#: person's name -- matched it, because "Kaya" ends in "ya" like any of a
#: thousand ordinary Turkish words; only requiring upper-case at the end
#: rules that out. See test_addressee_pattern_does_not_match_a_capitalised_name
#: and test_addressee_pattern_does_not_match_an_ordinary_body_sentence.
_ADDRESSEE_SUFFIX = r"(?:NA|NE|YA|YE|MAKAMA|YERLERİNE|BAŞKANLIĞINA)"
#: Trailing `\s+[0-9/]{1,12}` tolerates exactly one short *digits-and-slashes*
#: annotation after the suffix -- real vision-model OCR on the scanned
#: corpus (CY-012) places a handwritten reference number ('7/4/2413') on the
#: same line as the addressee when it reads that handwriting correctly, and
#: the stricter `$` anchor used to reject the whole line for it.
#:
#: Restricted to `[0-9/]`, not `\S`: a first attempt allowing any short token
#: caused a real regression, found by an A/B run against 45 real scans holding
#: the extracted text fixed and comparing old vs new parser output. "HAZİNE
#: VE MALİYE BAKANLIĞI" -- an institution's own letterhead line, not an
#: addressee -- false-matched because "MALİYE" ends in "YE" and "BAKANLIĞI"
#: is one short token; because _parse_addressee returns the *first* matching
#: line, this false match both won over the real addressee lower in the
#: document and (via _parse_sender_institution's shared break condition)
#: zeroed out gonderen_kurum recovery on every document sharing this
#: letterhead. Same failure family as the "Zeynep Kaya" case below, just
#: hitting an institution name instead of a person's name -- restricting the
#: annotation to a reference-number shape closes it while still matching
#: every real handwritten-reference case measured in the corpus.
_ADDRESSEE_LINE = re.compile(rf"^.{{6,40}}?{_ADDRESSEE_SUFFIX}(?:\s+[0-9/]{{1,12}})?\s*$")
#: A name-shaped word: Titlecase ("Ahmet") or an ALL-CAPS Turkish surname
#: ("GÜLER"). Official correspondence conventionally sets the surname (and
#: sometimes a title abbreviation, "Prof. Dr.") in full capitals -- the
#: original Titlecase-only pattern rejected "Yaşar GÜLER" outright.
#: Measured against the 23 hand-labelled real documents' `clean_text`
#: (OCR-error-free by construction): the Titlecase-only pattern lost
#: `imza_sahibi`/`imza_unvani` on 17/23 of them, all ALL-CAPS-surname
#: documents that datasets/sample/'s uniformly "Ahmet Yılmaz"-styled
#: synthetic corpus never exercised.
_NAME_WORD = r"(?:[A-ZÇĞİÖŞÜ][a-zçğıöşü]+|[A-ZÇĞİÖŞÜ]{2,})"
#: A personal name line in the signature block: 2-4 name-shaped words, no
#: digits. The leading lookahead requires at least one lower-case letter
#: somewhere on the line, so a line made entirely of ALL-CAPS words -- an
#: institution/letterhead line such as "TÜRKİYE BÜYÜK MİLLET MECLİSİ
#: BAŞKANLIĞI" -- can never match on its own; a genuine signature always
#: carries at least one Titlecase given name. This does not catch every
#: institution-name false-positive on its own (a *Titlecase-worded*
#: institution mention, e.g. "Türkiye Büyük Millet Meclisi" used in running
#: text, still matches this pattern) -- `_parse_signature` below additionally
#: rejects a candidate that looks like an institution name via
#: `INSTITUTION_PATTERN`, and relies on trying candidates in document order
#: (the real name line comes first) as the primary defense for the rest.
_PERSON_NAME_LINE = re.compile(
    rf"^(?=.*[a-zçğıöşü])(?:{_NAME_WORD}\.?\s+){{1,3}}{_NAME_WORD}$"
)
#: Words that mark a line as a title rather than a name.
_TITLE_HINT = re.compile(
    r"(Müdür|Başkan|Bakan|Vali|Kaymakam|Rektör|Dekan|Müsteşar|Amir|Şef|"
    r"Koordinatör|Uzman|Memur|İşletmen|Mühendis|Sekreter|Yardımcısı|a\.)",
    re.IGNORECASE,
)
#: Closing formulas that end the body; the signature block follows them.
_CLOSING_FORMULA = re.compile(
    r"(arz ederim|rica ederim|arz olunur|bilgilerinize|düzenlenmiştir)",
    re.IGNORECASE,
)


def _content_lines(text: str) -> list[str]:
    """Return non-empty, non-label lines in document order.

    Args:
        text: The extracted document text.

    Returns:
        Stripped content lines.
    """
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_sender_institution(lines: list[str]) -> Optional[str]:
    """Read the letterhead: the lines between "T.C." and the first side-heading.

    Args:
        lines: Content lines in document order.

    Returns:
        The institution name, or None when there is no letterhead.
    """
    try:
        start = next(i for i, line in enumerate(lines) if _TC_LINE.match(line))
    except StopIteration:
        return None

    collected = []
    for line in lines[start + 1 :]:
        if _ANY_LABEL_LINE.match(line) or _ADDRESSEE_LINE.match(line):
            break
        collected.append(line)
        if len(collected) >= 3:
            break
    return " ".join(collected) if collected else None


def _parse_addressee(lines: list[str]) -> Optional[str]:
    """Find the addressee line (m.14): upper-case with a dative suffix.

    Args:
        lines: Content lines in document order.

    Returns:
        The addressee, or None when no line matches.
    """
    for index, line in enumerate(lines):
        if _ANY_LABEL_LINE.match(line) or _TC_LINE.match(line):
            continue
        if _ADDRESSEE_LINE.match(line):
            # A parenthesised unit name may follow on the next line.
            suffix = ""
            if index + 1 < len(lines) and lines[index + 1].startswith("("):
                suffix = " " + lines[index + 1]
            return (line + suffix).strip()
    return None


def _parse_signature(lines: list[str]) -> dict[str, str]:
    """Read the signature block (m.17): name above, title below.

    Args:
        lines: Content lines in document order.

    Returns:
        Mapping possibly containing `imza_sahibi` and `imza_unvani`.
    """
    # The signature block is what follows the closing formula; fall back to the
    # tail of the document when no formula is present (e.g. a tutanak).
    start = 0
    for index, line in enumerate(lines):
        if _CLOSING_FORMULA.search(line):
            start = index + 1
    tail = [
        line
        for line in lines[start:][-4:]
        if not _ANY_LABEL_LINE.match(line) and line.lower() != "imza"
    ]

    # A trailing name alone is not a signature. In an unsigned petition the last
    # line is simply the applicant's name, and claiming it as `imza_sahibi` would
    # mask a genuine 3071 m.4 omission. Require corroboration: a title line after
    # the name, an explicit "İmza" marker, or an institutional letterhead -- an
    # official letter is signed by definition (m.17).
    # Turkish casing matters here: "İmza".lower() yields "i̇mza", a dotted i plus a
    # combining dot, which never equals "imza".
    has_signature_marker = any(
        normalize_value(line).rstrip(":") == "imza" for line in lines[start:]
    )
    has_letterhead = any(_TC_LINE.match(line) for line in lines)

    parsed: dict[str, str] = {}
    for index, line in enumerate(tail):
        if (
            not _PERSON_NAME_LINE.match(line)
            or _TITLE_HINT.search(line)
            # A Titlecase-worded institution mention ("Türkiye Büyük Millet
            # Meclisi") still matches _PERSON_NAME_LINE -- see that pattern's
            # own docstring. Reject any candidate shaped like an institution
            # name outright rather than accepting it as a person.
            or INSTITUTION_PATTERN.search(line)
        ):
            continue
        title = next(
            (
                candidate
                for candidate in tail[index + 1 :]
                if _TITLE_HINT.search(candidate)
            ),
            None,
        )
        if title is None and not has_signature_marker and not has_letterhead:
            break
        parsed["imza_sahibi"] = line
        if title is not None:
            parsed["imza_unvani"] = title
        break
    return parsed


def parse_positional_fields(text: str) -> dict[str, Any]:
    """Extract the fields the regulation places by position rather than by label.

    Başlık (m.10), muhatap (m.14) and the imza block (m.17) carry no side-heading,
    so they are located structurally. These are heuristics rather than prescribed
    labels, so each pattern is deliberately strict: reporting nothing is far
    better than inventing a value, which would mask a genuine omission.

    Args:
        text: The extracted document text.

    Returns:
        Mapping of `EvrakField` names to parsed values, containing only what was
        confidently located.
    """
    lines = _content_lines(text)
    parsed: dict[str, Any] = {}

    institution = _parse_sender_institution(lines)
    if institution:
        parsed["gonderen_kurum"] = institution

    addressee = _parse_addressee(lines)
    if addressee:
        parsed["muhatap"] = addressee

    parsed.update(_parse_signature(lines))
    return parsed


def parse_labelled_fields(text: str) -> dict[str, Any]:
    """Extract the fields the regulation prescribes as labelled side-headings.

    Args:
        text: The extracted document text.

    Returns:
        Mapping of `EvrakField` names to parsed values, containing only the fields
        actually found. Never guesses: an absent label yields no entry.
    """
    parsed: dict[str, Any] = {}

    for name, pattern in SINGLE_VALUE_PATTERN.items():
        match = pattern.search(text)
        if match:
            value = _clean(match.group(1))
            if value:
                parsed[name] = value

    for name, pattern in LIST_VALUE_PATTERN.items():
        match = pattern.search(text)
        if match:
            items = _split_list(match.group(1))
            if items:
                parsed[name] = items

    # Fallback for the unlabelled date real correspondence routinely places at
    # the right of the Sayı line (see _UNLABELLED_DATE_ON_SAYI_LINE) -- tried
    # only when the labelled "Tarih:" form above found nothing, so a document
    # that does label it is unaffected.
    if "tarih" not in parsed:
        match = _UNLABELLED_DATE_ON_SAYI_LINE.search(text)
        if match:
            value = _clean(match.group(1))
            if value:
                parsed["tarih"] = value

    # Second fallback, tried only when the same-line form above also found
    # nothing -- see _UNLABELLED_DATE_ON_LINE_AFTER_SAYI's own docstring.
    if "tarih" not in parsed:
        match = _UNLABELLED_DATE_ON_LINE_AFTER_SAYI.search(text)
        if match:
            value = _clean(match.group(1))
            if value:
                parsed["tarih"] = value

    # Positional fields fill in only where a labelled value was not already found.
    for name, value in parse_positional_fields(text).items():
        parsed.setdefault(name, value)

    return parsed


#: Fields for which the parser is authoritative in BOTH directions: if the
#: regulation prescribes how the field appears and the parser cannot find it, the
#: field is genuinely absent and a model value for it is discarded.
#:
#: Deliberately excludes fields whose presentation is not prescribed and which the
#: parser therefore cannot rule out:
#:   - `adres` / `iletisim`: a petition often writes these without a label.
#:   - `gizlilik_derecesi` / `ivedilik`: appear as standalone stamps
#:     ("HİZMETE ÖZEL", "ACELE") rather than as side-headings.
#:   - `basvuran_adi`: has no parser support at all.
#: For those, an absent parse means "unknown", not "absent", so the model is
#: still trusted.
AUTHORITATIVE_FIELD: frozenset[str] = frozenset(
    {
        "sayi",
        "tarih",
        "konu",
        "ilgi",
        "ekler",
        "muhatap",
        "gonderen_kurum",
        "imza_sahibi",
        "imza_unvani",
    }
)

#: Fields whose empty value is a list rather than None.
_LIST_FIELD: frozenset[str] = frozenset({"ilgi", "ekler"})

#: The five header fields RYUEHY's compliance check reads and this project's
#: extraction-acceptance gate (see FallbackDocumentExtractor's
#: `header_field_probe`) uses to decide whether an extraction is trustworthy.
#: A document-wide prose-readability score (`ExtractedDocument.quality_ratio`)
#: cannot see whether the header block survived -- a garbled `sayi` sitting in
#: an otherwise clean page still reads as fine Turkish prose overall. Counting
#: these five instead is a direct measurement of the actual failure the
#: compliance checker cares about.
HEADER_FIELD: tuple[str, ...] = ("sayi", "tarih", "konu", "muhatap", "gonderen_kurum")


def count_header_fields(text: str) -> int:
    """Count how many of `HEADER_FIELD` are recoverable from `text`.

    Reuses `parse_labelled_fields` rather than re-implementing detection, so
    this always measures exactly what the compliance pipeline itself would
    recover -- no separate, driftable notion of "found".

    Args:
        text: Extracted document text (typically just page 1 -- see the
            extraction-acceptance gate's own reasoning for why whole-document
            scoring hides a page-1 failure behind an attached letter's own
            header on a later page).

    Returns:
        The number of `HEADER_FIELD` keys with a non-empty parsed value,
        from 0 to `len(HEADER_FIELD)`.
    """
    parsed = parse_labelled_fields(text)
    return sum(1 for name in HEADER_FIELD if parsed.get(name))


#: `AUTHORITATIVE_FIELD` members eligible for evidence-based rescue (see
#: `merge_parsed_over_model`) when the parser found nothing but the model's
#: value is genuinely grounded in the document text. Deliberately narrower
#: than `AUTHORITATIVE_FIELD`:
#:
#: * `imza_sahibi`/`imza_unvani`'s absence from `_parse_signature`'s output
#:   is a *considered* decision, not a coverage gap -- that function
#:   deliberately declines a bare trailing name without a title line,
#:   signature marker or letterhead to corroborate it (the unsigned-petition
#:   guard, see `UNSIGNED_PETITION`'s own test). The name is almost always
#:   still sitting right there in the text either way, so a plain
#:   substring-grounding check would rescue it and reintroduce exactly the
#:   omission that guard exists to catch.
#: * `ilgi`/`ekler` name specific document references; an invented one
#:   carries the same fabrication risk `imza_sahibi` does, so they stay
#:   strict too.
_EVIDENCE_RESCUABLE_FIELD: frozenset[str] = frozenset(
    {"sayi", "tarih", "konu", "muhatap", "gonderen_kurum"}
)

#: The subset of `_EVIDENCE_RESCUABLE_FIELD` also eligible for the
#: token-overlap fallback (see `_token_overlap`), below the exact substring
#: check. Deliberately narrower still: `muhatap` and `gonderen_kurum` name a
#: specific person or institution, which a model realistically reorders
#: ("Ankara Milletvekili İdris ŞAHİN" for a document that writes it name-
#: first) but does not synthesise wholesale, since a person/institution
#: name is not something a model paraphrases the way it paraphrases a
#: topic. `konu`/`tarih`/`sayi` stay on the strict substring check only --
#: measured live against qwen3.5:9b on CY-010, a document with no "Konu:"
#: line at all: the model produced a `konu` value built by lightly
#: rewording body vocabulary ("...istemlerine ilişkin ilgi önergenizde
#: yer alan sorularınız..." into "...istemlerine ilişkin soruların
#: cevabı"), which scored 0.857 token overlap -- comfortably past
#: `TOKEN_OVERLAP_THRESHOLD` -- despite being a synthesised summary, not an
#: extracted value. `konu` is exactly the shape of field a model is
#: naturally inclined to summarise rather than quote, so it is the one
#: `_EVIDENCE_RESCUABLE_FIELD` member the token-overlap fallback must not
#: reach; `tarih`/`sayi` are excluded too since neither field's failure
#: mode is "same value, different word order" the way a name is.
_TOKEN_OVERLAP_ELIGIBLE_FIELD: frozenset[str] = frozenset({"muhatap", "gonderen_kurum"})


def _header_region(text: str) -> str:
    """Return `text` up to (excluding) the first addressee or closing-formula line.

    The header block (Sayı/Tarih/Konu, m.11-13) always precedes both in a
    well-formed document. Used to scope `tarih`'s evidence-based rescue in
    `merge_parsed_over_model`: without this, a leave request's start date
    sitting in the body would ground exactly as well as a genuine header
    date, resurrecting the specific failure mode `merge_parsed_over_model`'s
    own docstring already names ("lifting a leave start date ... into
    `tarih`") the moment the substring check is loosened for anything else.

    Args:
        text: Full extracted document text.

    Returns:
        The leading lines, joined, or the whole text when neither an
        addressee nor a closing formula is found.
    """
    lines = _content_lines(text)
    for index, line in enumerate(lines):
        if _ADDRESSEE_LINE.match(line) or _CLOSING_FORMULA.search(line):
            return "\n".join(lines[:index])
    return text


def _token_overlap(value: str, haystack: str) -> float:
    """Share of `value`'s significant tokens (length > 2) present in `haystack`.

    A tolerant fallback below the exact substring check in
    `merge_parsed_over_model`: a model may correctly report a value while
    reordering it relative to how it sits in the source. Measured live
    against qwen3.5:9b on a real document (CY-033), the model returned
    "Ankara Milletvekili İdris ŞAHİN" for a `muhatap` the text itself
    writes as "Sayın İdris ŞAHİN\\nAnkara Milletvekili" -- the same two
    facts (name, title), reversed order, which a plain substring check
    rejects outright even though nothing was invented.

    Same shape and threshold (`TOKEN_OVERLAP_THRESHOLD`) as
    `app.ai.verification.draft_verifier`'s own `_token_overlap`,
    reimplemented rather than imported so this module's grounding check
    folds through `normalize_value` -- its own existing convention, which
    strips punctuation -- instead of introducing `draft_verifier`'s `_fold`
    (which keeps it) as a second folding contract here.

    Args:
        value: The candidate value, unfolded.
        haystack: The trusted text to check against, unfolded.

    Returns:
        The overlap in [0, 1]. Values with fewer than two significant
        tokens score 0.0 -- a single token is not meaningful evidence on
        its own, the same reasoning `INSTITUTION_PATTERN`'s multi-word
        requirement and `_PERSON_NAME_LINE`'s 2-4 word shape both rely on.
    """
    tokens = [token for token in normalize_value(value).split() if len(token) > 2]
    if len(tokens) < 2:
        return 0.0
    folded_haystack = normalize_value(haystack)
    return sum(1 for token in tokens if token in folded_haystack) / len(tokens)


def merge_parsed_over_model(
    model_fields: dict[str, Any], parsed: dict[str, Any], document_text: str = ""
) -> dict[str, Any]:
    """Combine deterministically parsed values with model output.

    The parser wins in both directions for `AUTHORITATIVE_FIELD`:

    * where it found a value, that value replaces the model's;
    * where it found nothing, the model's value is discarded -- *unless*
      `document_text` is given, the field is in `_EVIDENCE_RESCUABLE_FIELD`,
      and the model's value is genuinely grounded -- a folded substring
      match (via `normalize_value`, same as `is_blank`'s own folding), or,
      for `muhatap`/`gonderen_kurum` specifically
      (`_TOKEN_OVERLAP_ELIGIBLE_FIELD`) and failing the substring check, a
      token-overlap match (`_token_overlap`, same `TOKEN_OVERLAP_THRESHOLD`
      `draft_verifier` uses) for a name the model reported correctly but
      reordered relative to the source (see `_token_overlap`'s own
      docstring for the live CY-033 case this covers, and
      `_TOKEN_OVERLAP_ELIGIBLE_FIELD`'s own docstring for why `konu` in
      particular must stay off this path -- a live counter-example on
      CY-010, where it rescued a model-synthesised summary instead of a
      reordered extraction). Grounding checks run against the document
      text (`_header_region` for `tarih` specifically). This
      matters: measured directly against 23 hand-labelled real documents,
      the parser is structurally unable to reach some of these values at
      all -- `muhatap` when the addressee is a named person rather than a
      dative-suffixed institution ("Sayın Ceylan AKÇA CUPOLO"), a
      `gonderen_kurum` with no "T.C." letterhead line -- while the model
      reads them correctly every time in that same measurement. Blanket
      discard was silently turning those into false "missing information"
      findings.
    * discarding remains unconditional for a field outside
      `_EVIDENCE_RESCUABLE_FIELD` (see that set's own docstring for why),
      and for any field when `document_text` is omitted -- every existing
      caller that does not pass it keeps exactly today's strict behaviour.

    The regulation prescribes how these fields appear, so a missing label
    together with no grounded model value means the field is genuinely
    absent -- and a model that filled it anyway would convert an incomplete
    document into an apparently compliant one, hiding the very omission this
    pipeline exists to report. The original, still-live example: the model
    inventing the stock addressee "İLGİLİ MAKAMA" for a letter that has
    none -- "İLGİLİ MAKAMA" is not itself grounded in such a letter's text,
    so it is discarded exactly as before.

    Fields outside `AUTHORITATIVE_FIELD` are left exactly as the model produced
    them, because for those an absent parse means "unknown", not "absent".

    Args:
        model_fields: The model's `EvrakField` dump.
        parsed: Output of `parse_labelled_fields`.
        document_text: The full extracted document text, for evidence-based
            rescue. Omit (the default, `""`) to keep every unparsed
            `AUTHORITATIVE_FIELD` value discarded unconditionally.

    Returns:
        The merged field mapping.
    """
    merged = dict(model_fields)
    header_text = _header_region(document_text) if document_text else ""
    for name in AUTHORITATIVE_FIELD:
        if name in parsed:
            continue
        if document_text and name in _EVIDENCE_RESCUABLE_FIELD:
            value = model_fields.get(name)
            if not is_blank(value):
                haystack = header_text if name == "tarih" else document_text
                text_value = str(value)
                grounded = normalize_value(text_value) in normalize_value(haystack)
                if not grounded and name in _TOKEN_OVERLAP_ELIGIBLE_FIELD:
                    grounded = _token_overlap(text_value, haystack) >= TOKEN_OVERLAP_THRESHOLD
                if grounded:
                    # Grounded: keep the model's value, already sitting in
                    # `merged` from the initial `dict(model_fields)` copy.
                    continue
        merged[name] = [] if name in _LIST_FIELD else None
    merged.update(parsed)
    return merged


def format_parsed_fields(parsed: dict[str, Any]) -> str:
    """Render already-parsed fields as a prompt note so the model skips them.

    Args:
        parsed: Output of `parse_labelled_fields`.

    Returns:
        A Turkish note listing the resolved fields, or an empty string.
    """
    if not parsed:
        return ""
    listed = ", ".join(sorted(parsed))
    return (
        f"\n\nNot: Şu alanlar zaten okundu, bunlarla ilgilenme: {listed}. "
        "Yalnızca kalan alanlara odaklan."
    )


def parsed_or_none(parsed: dict[str, Any], name: str) -> Optional[Any]:
    """Return a parsed value if present.

    Args:
        parsed: Output of `parse_labelled_fields`.
        name: Field name.

    Returns:
        The parsed value or None.
    """
    return parsed.get(name)
