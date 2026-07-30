"""Deterministic extraction of the labelled header fields of an official document.

The Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik *specifies*
the header layout: "Sayı:" is a side-heading (m.11), "Tarih:" sits on the same line
at the right margin (m.12), "Konu:" goes one line below (m.13), "İlgi:" lists the
referenced documents (m.15) and "Ek:" follows the signature (m.18). Because the
format is prescribed rather than free-form, these values can be read with regular
expressions at far higher accuracy than a small language model achieves.

That matters concretely. Measured on qwen3:8b, asking for a single field returns
`sayi` correctly, but asking for three at once returns `sayi` as null and can send
another field into a repeating-token loop until the generation budget is spent.
Parsing the prescribed labels here removes those fields from the model's burden and
leaves it the genuinely unstructured judgement (muhatap, the signature block).

Values parsed here take precedence over model output for the same field.
"""

import re
from typing import Any, Optional

from app.ai.compliance.checker import normalize_value

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
_VALUE_TAIL = (
    rf"[ \t]*[:：][ \t]*(.+?)"
    rf"(?=[ \t]+(?:{_LABEL_ALTERNATION})[ \t]*[:：]|[ \t]*$)"
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
#: "T.C." header line (m.10).
_TC_LINE = re.compile(r"^\s*T\s*\.?\s*C\s*\.?\s*$", re.IGNORECASE)
#: An addressee line: upper-case and carrying a Turkish dative suffix (m.14),
#: e.g. "ÖRNEK VALİLİĞİNE", "İLGİLİ MAKAMA", "DAĞITIM YERLERİNE".
_ADDRESSEE_LINE = re.compile(
    r"^[^a-zçğıöşü]{6,}?(?:NA|NE|YA|YE|MAKAMA|YERLERİNE|BAŞKANLIĞINA)\s*$"
)
#: A personal name line in the signature block: 2-4 capitalised words, no digits.
_PERSON_NAME_LINE = re.compile(
    r"^(?:[A-ZÇĞİÖŞÜ][a-zçğıöşü]+\.?\s+){1,3}[A-ZÇĞİÖŞÜ][a-zçğıöşü]+$"
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
        if not _PERSON_NAME_LINE.match(line) or _TITLE_HINT.search(line):
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

    # Positional fields fill in only where a labelled value was not already found.
    for name, value in parse_positional_fields(text).items():
        parsed.setdefault(name, value)

    return parsed


def merge_parsed_over_model(
    model_fields: dict[str, Any], parsed: dict[str, Any]
) -> dict[str, Any]:
    """Overlay deterministically parsed values on top of model output.

    Parsed values win for the fields they cover: the label they were read from is
    prescribed by the regulation, which is stronger evidence than a model guess.
    Fields the parser does not cover are left exactly as the model produced them.

    Args:
        model_fields: The model's `EvrakField` dump.
        parsed: Output of `parse_labelled_fields`.

    Returns:
        The merged field mapping.
    """
    merged = dict(model_fields)
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
