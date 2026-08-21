"""Type-aware canonical forms for the values a draft can be checked against.

``draft_verifier`` decides whether a concrete claim in a draft is grounded by
folding both sides to lowercase ASCII and asking whether one contains the other.
That works for text and fails for *typed* values, because two spellings of the
same fact fold to different strings:

    kaynak: "01.03.2026"      taslak: "1 Mart 2026"
    kaynak: "Madde 11"        taslak: "m. 11"
    kaynak: "125.000,00 TL"   taslak: "125.000 TL"
    kaynak: "E-44444444-841-77"  taslak: "E-44444444/841/77"

The measured baseline (``evaluation/reports/all-baseline.md``) shows this is not
a hypothetical: every false positive the deterministic draft gate produces is
one of these, and each one costs a correct draft a human-in-the-loop
interruption. The token-overlap fallback cannot rescue them either -- "12 Mart
2026" against "12 03 2026" shares only the year once short tokens are dropped,
which is 0.5 overlap against a 0.75 threshold.

So each type gets a canonical form and values are compared on it. This is
*lossless normalisation, not fuzzy matching*: a canonical form changes how a
value is written, never what it means. Two different dates must never collapse
onto one canonical string, which is why the month table is exact and an
unparseable value returns None (fall back to the textual comparison) rather than
a best guess.

Deliberately excluded: anything semantic. Numbers, dates and amounts need
equality, not similarity -- "12.03.2026" and "13.03.2026" are one character
apart and mean entirely different things.
"""

import re
import unicodedata
from typing import Optional

__all__ = [
    "canonical_date",
    "canonical_document_number",
    "canonical_amount",
    "canonical_legislation",
    "canonical_for_kind",
]

#: Turkish month names as the regulation writes them, folded to ASCII.
_MONTHS: dict[str, int] = {
    "ocak": 1,
    "subat": 2,
    "mart": 3,
    "nisan": 4,
    "mayis": 5,
    "haziran": 6,
    "temmuz": 7,
    "agustos": 8,
    "eylul": 9,
    "ekim": 10,
    "kasim": 11,
    "aralik": 12,
}

_TURKISH_MAP = str.maketrans(
    {
        "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i",
        "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
    }
)

_NUMERIC_DATE = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$")
#: ISO 8601 ("2026-04-09") -- a source document's own extracted text (a PDF's
#: literal "Dates: 2026-04-09 to 2026-05-06", say) uses this shape as often as
#: the Turkish DD.MM.YYYY one _NUMERIC_DATE handles. Checked before it: a
#: leading 4-digit group can never match _NUMERIC_DATE's first (1-2 digit) day
#: group, so the two patterns never contend for the same input, but ordering
#: this one first keeps the "most specific first" reading intact.
_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_TEXTUAL_DATE = re.compile(r"^(\d{1,2})\s+([a-z]+)\s+(\d{4})$")

#: "4982 sayılı" -> the law's number.
_LAW_NUMBER = re.compile(r"^(\d{3,5})\s+sayili$")
#: "madde 12" / "m. 7" / "m.7" -> the article number.
_ARTICLE = re.compile(r"^(?:madde|m)\s*\.?\s*(\d+)$")

#: A currency written in any of the forms the corpus uses.
_CURRENCY_ALIASES = {
    "tl": "TRY",
    "try": "TRY",
    "lira": "TRY",
    "euro": "EUR",
    "eur": "EUR",
    "usd": "USD",
    "dolar": "USD",
}
_AMOUNT = re.compile(r"^([\d.,\s]+?)\s*(tl|try|lira|euro|eur|usd|dolar)$")

#: Currency symbols are dropped outright by the ASCII fold, so they are spelled
#: out before folding rather than listed in the alternation above -- where they
#: could never match.
_CURRENCY_SYMBOLS = {"₺": " tl", "€": " eur", "$": " usd"}


def _fold(text: str) -> str:
    """Fold to lowercase ASCII with whitespace collapsed, keeping punctuation."""
    folded = (text or "").translate(_TURKISH_MAP)
    decomposed = unicodedata.normalize("NFKD", folded)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", ascii_text).strip()


def canonical_date(value: str) -> Optional[str]:
    """Render a Turkish date in ISO form.

    Handles the formats the regulation, its drafts, and an uploaded
    document's own extracted text actually use -- ``12.03.2026`` (also with
    ``/`` or ``-``), ``12 Mart 2026``, and ISO 8601's ``2026-03-12``.

    Args:
        value: The date as written.

    Returns:
        ``YYYY-MM-DD``, or None when the value is not a date this understands.
        None is deliberate: an unrecognised value must fall back to textual
        comparison rather than be coerced into a wrong canonical form.
    """
    folded = _fold(value)

    match = _ISO_DATE.match(folded)
    if match:
        year, month, day = (int(part) for part in match.groups())
    else:
        match = _NUMERIC_DATE.match(folded)
        if match:
            day, month, year = (int(part) for part in match.groups())
        else:
            match = _TEXTUAL_DATE.match(folded)
            if not match:
                return None
            day_text, month_name, year_text = match.groups()
            if month_name not in _MONTHS:
                return None
            day, month, year = int(day_text), _MONTHS[month_name], int(year_text)

    # Reject impossible dates rather than normalising them; a draft claiming
    # "32.13.2026" is a defect the verifier should still surface as ungrounded.
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def canonical_document_number(value: str) -> Optional[str]:
    """Strip separator variation from an official document number.

    ``E-44444444-841-77``, ``E-44444444/841/77`` and ``E 44444444 841 77`` are
    the same number written three ways. Only the alphanumeric run is
    significant.

    Args:
        value: The document number as written.

    Returns:
        The separator-free form, or None when the value carries no digits (in
        which case it is not a document number and must not be treated as one).
    """
    folded = _fold(value)
    stripped = re.sub(r"[^a-z0-9]+", "", folded)
    if not stripped or not any(char.isdigit() for char in stripped):
        return None
    return stripped


def canonical_amount(value: str) -> Optional[str]:
    """Render a monetary amount as a decimal plus an ISO-ish currency code.

    Turkish notation uses ``.`` for thousands and ``,`` for decimals, so
    ``125.000,00 TL`` and ``125.000 TL`` and ``125000 TL`` are the same amount.
    Trailing zero decimals are dropped so the first two compare equal.

    Args:
        value: The amount as written.

    Returns:
        ``"<amount> <CURRENCY>"``, or None when the value is not a recognised
        amount.
    """
    spelled = value or ""
    for symbol, word in _CURRENCY_SYMBOLS.items():
        spelled = spelled.replace(symbol, word)

    match = _AMOUNT.match(_fold(spelled))
    if not match:
        return None

    digits, currency = match.groups()
    digits = re.sub(r"\s+", "", digits)

    if "," in digits:
        whole, _, fraction = digits.rpartition(",")
        whole = whole.replace(".", "")
        fraction = fraction.rstrip("0")
    else:
        whole, fraction = digits.replace(".", ""), ""

    whole = whole.lstrip("0") or "0"
    if not whole.isdigit() or (fraction and not fraction.isdigit()):
        return None

    normalized = f"{whole}.{fraction}" if fraction else whole
    return f"{normalized} {_CURRENCY_ALIASES[currency]}"


def canonical_legislation(value: str) -> Optional[str]:
    """Render a legislation citation in one of two canonical shapes.

    ``4982 sayılı`` becomes ``kanun:4982``; ``madde 11``, ``m. 11`` and ``m.11``
    all become ``madde:11``. The two are kept as separate namespaces because a
    law number and an article number are different facts and a draft citing
    article 4982 of something is not grounded by a source mentioning law 4982.

    Args:
        value: The citation as written.

    Returns:
        The canonical citation, or None when the value is not one.
    """
    folded = _fold(value).rstrip(".")

    match = _LAW_NUMBER.match(folded)
    if match:
        return f"kanun:{int(match.group(1))}"

    match = _ARTICLE.match(folded)
    if match:
        return f"madde:{int(match.group(1))}"

    return None


#: Claim kind -> canonicaliser. Keyed by the kind labels ``draft_verifier``
#: already uses, so the two cannot drift apart silently.
_BY_KIND = {
    "tarih": canonical_date,
    "sayı": canonical_document_number,
    "tutar": canonical_amount,
    "mevzuat": canonical_legislation,
}


def canonical_for_kind(kind: str, value: str) -> Optional[str]:
    """Canonicalise a value according to its claim kind.

    Args:
        kind: The claim kind (``tarih``, ``sayı``, ``tutar``, ``mevzuat``).
        value: The value as written.

    Returns:
        The canonical form, or None when the kind has no canonicaliser (notably
        ``kurum``, where names are compared textually) or the value does not
        parse.
    """
    canonicalise = _BY_KIND.get(kind)
    return canonicalise(value) if canonicalise else None
