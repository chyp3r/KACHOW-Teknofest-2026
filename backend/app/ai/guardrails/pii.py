"""Deterministic Turkish PII detection over extracted document text.

Same rationale as ``app.ai.compliance.field_parser``'s regex-first approach
(see its module docstring): a TCKN or IBAN is a structurally defined value
with a checksum, not a free-form fact a model has to infer -- regex plus the
real checksum algorithm is both faster and more accurate than a model call on
a path that runs on every upload and every guardrail-scanned reply. A finding
carries only a masked preview, never the raw value, so a PII finding does not
itself become a second unencrypted copy of the PII it flags (in logs, in
``GuardrailEventModel.reasons``, or anywhere else it travels).
"""

import re
from typing import Optional

from pydantic import BaseModel, Field

#: Turkish national ID number: exactly 11 digits, not a substring of a longer
#: run (a document number like "12345678901234" must not match).
_TCKN_PATTERN = re.compile(r"(?<!\d)\d{11}(?!\d)")

#: Turkish IBAN: "TR" + 24 digits, optionally space-grouped as banks print it.
_IBAN_PATTERN = re.compile(
    r"\bTR\d{2}(?:[ ]?\d{4}){5}[ ]?\d{2}\b", re.IGNORECASE
)

#: Turkish phone numbers: optional +90/0 prefix, mobile (5xx) or landline
#: (2xx-4xx) area code, then 7 digits, loosely space/dot/dash-grouped. Kept
#: permissive on separators since real documents format phone numbers every
#: way imaginable; confidence (not the pattern) carries the uncertainty.
_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+90[ ]?|0)?(5\d{2}|2\d{2}|3\d{2}|4\d{2})"
    r"[ .\-]?\d{3}[ .\-]?\d{2}[ .\-]?\d{2}(?!\d)"
)
#: A phone label nearby raises confidence -- distinguishes a genuine phone
#: number from an incidental 10-digit run (e.g. part of a longer reference).
_PHONE_CONTEXT = re.compile(r"\b(tel|telefon|gsm|cep)\b", re.IGNORECASE)

#: Address heuristic: a content line scores as an address when it carries a
#: street/unit keyword. Mirrors the vocabulary ``field_parser.py`` already
#: knows to expect in an ``Adres:``-labelled value, but scans free text since
#: an address in a petition's body often carries no label at all.
_ADDRESS_KEYWORDS = re.compile(
    r"\b(mahalle(si)?|mah\.|cadde(si)?|cad\.|sokak|sok\.|bulvar[ıi]?|"
    r"apartman[ıi]?|blok|kat\s*:?\s*\d|daire\s*:?\s*\d|no\s*:?\s*\d+)\b",
    re.IGNORECASE,
)

#: Below this many keyword hits a line is not confidently an address.
_ADDRESS_MIN_KEYWORD_HITS = 2


class PiiFinding(BaseModel):
    """One PII pattern match, carrying only a masked preview of the value.

    ``confidence`` lets callers apply ``GuardrailPolicy.pii_confidence_floor``
    to separate a real finding from pattern noise (see
    ``app.ai.guardrails.sensitivity.assess``) -- it is never itself sensitive,
    so it is safe to log or persist alongside the finding.
    """

    kind: str = Field(description="'tckn' | 'iban' | 'telefon' | 'adres'.")
    preview: str = Field(description="Maskelenmiş önizleme; ham değer taşımaz.")
    confidence: float = Field(description="0-1 arası güven skoru.")


def _mask(value: str, *, keep_start: int = 2, keep_end: int = 2) -> str:
    """Redact the middle of a value, keeping only a few characters at each end.

    Args:
        value: The raw matched value.
        keep_start: Characters to keep visible at the start.
        keep_end: Characters to keep visible at the end.

    Returns:
        A masked preview, e.g. ``"12*******34"``.
    """
    stripped = value.strip()
    if len(stripped) <= keep_start + keep_end:
        return "*" * len(stripped)
    middle = "*" * (len(stripped) - keep_start - keep_end)
    # `stripped[-0:]` is the whole string, not "the last zero characters" --
    # Python's `-0 == 0`, so a naive `stripped[-keep_end:]` leaks the entire
    # value back out whenever a caller asks to keep 0 trailing characters
    # (as the address finder does). Guard the zero case explicitly.
    tail = stripped[-keep_end:] if keep_end > 0 else ""
    return f"{stripped[:keep_start]}{middle}{tail}"


def _tckn_checksum_valid(digits: str) -> bool:
    """Validate an 11-digit string against the Turkish TCKN checksum algorithm.

    Args:
        digits: Exactly 11 ASCII digit characters.

    Returns:
        True when both check digits (positions 10 and 11) are consistent
        with the first nine, and the number does not start with 0.
    """
    if digits[0] == "0":
        return False
    nums = [int(char) for char in digits]
    odd_sum = nums[0] + nums[2] + nums[4] + nums[6] + nums[8]
    even_sum = nums[1] + nums[3] + nums[5] + nums[7]
    tenth = (odd_sum * 7 - even_sum) % 10
    if tenth != nums[9]:
        return False
    eleventh = sum(nums[:10]) % 10
    return eleventh == nums[10]


def _iban_checksum_valid(iban: str) -> bool:
    """Validate a Turkish IBAN against the ISO 7064 MOD97-10 checksum.

    Args:
        iban: The IBAN with spaces removed, upper-cased.

    Returns:
        True when the checksum holds and the length matches a Turkish IBAN
        (26 characters: "TR" + 24 digits).
    """
    if len(iban) != 26 or not iban.startswith("TR"):
        return False
    rearranged = iban[4:] + iban[:4]
    try:
        # A single character's base-36 value is exactly ISO 7064's letter
        # rule (A=10 ... Z=35) for letters, and the digit's own value for
        # digits -- no separate lookup table needed.
        numeric = "".join(str(int(char, 36)) for char in rearranged)
    except ValueError:
        return False
    return int(numeric) % 97 == 1


def _find_tckn(text: str) -> list[PiiFinding]:
    findings = []
    for match in _TCKN_PATTERN.finditer(text):
        digits = match.group(0)
        if _tckn_checksum_valid(digits):
            findings.append(
                PiiFinding(kind="tckn", preview=_mask(digits), confidence=0.95)
            )
    return findings


def _find_iban(text: str) -> list[PiiFinding]:
    findings = []
    for match in _IBAN_PATTERN.finditer(text):
        raw = match.group(0)
        normalized = raw.replace(" ", "").upper()
        if _iban_checksum_valid(normalized):
            findings.append(
                PiiFinding(kind="iban", preview=_mask(raw, keep_start=4, keep_end=2), confidence=0.95)
            )
    return findings


def _find_phone(text: str) -> list[PiiFinding]:
    findings = []
    for match in _PHONE_PATTERN.finditer(text):
        start = max(0, match.start() - 20)
        nearby = text[start : match.start()]
        confidence = 0.85 if _PHONE_CONTEXT.search(nearby) else 0.55
        findings.append(
            PiiFinding(kind="telefon", preview=_mask(match.group(0)), confidence=confidence)
        )
    return findings


def _find_address(text: str) -> list[PiiFinding]:
    findings = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        hits = len(_ADDRESS_KEYWORDS.findall(stripped))
        if hits >= _ADDRESS_MIN_KEYWORD_HITS:
            confidence = min(0.5 + 0.1 * hits, 0.9)
            findings.append(
                PiiFinding(
                    kind="adres",
                    preview=_mask(stripped, keep_start=6, keep_end=0).rstrip("*") + "…",
                    confidence=confidence,
                )
            )
    return findings


def find_pii(text: str) -> list[PiiFinding]:
    """Scan text for Turkish PII patterns.

    Deliberately unfiltered by confidence here -- callers (chiefly
    ``app.ai.guardrails.sensitivity.assess``) apply
    ``GuardrailPolicy.pii_confidence_floor`` so the threshold lives in one
    tunable place rather than being baked into the scanner.

    Args:
        text: Raw text to scan (document text, or a generated reply for the
            output-side leakage check).

    Returns:
        Every pattern match found, each with only a masked preview.
    """
    if not text:
        return []
    return [
        *_find_tckn(text),
        *_find_iban(text),
        *_find_phone(text),
        *_find_address(text),
    ]
