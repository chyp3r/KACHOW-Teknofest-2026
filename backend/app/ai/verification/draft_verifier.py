"""Deterministic grounding and structure checks for generated drafts.

This replaces the LLM editor node, which had two problems beyond its cost.

*Cost*: the editor's structured output had to re-emit ``final_draft`` in full, so
every draft was generated twice. On Apple Silicon at roughly 28 tokens/second an
800-token draft costs about 29 seconds, and the editor doubled that -- more than
half of the entire latency budget spent re-typing text the writer had already
produced correctly.

*Validity*: the editor was the same model, scoring its own output. A model that
invents a document number does not reliably notice that it invented it, so the
confidence score measured fluency rather than faithfulness.

Checking groundedness is a set-membership question -- does every number, date and
institution in the draft trace back to the source or the retrieved legislation?
-- which string matching answers exactly, instantly, and reproducibly.
"""

import logging
import re
import unicodedata
from typing import Any, Iterable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

#: Drafts scoring below this need a human before they can be sent.
MIN_AUTOMATED_CONFIDENCE_SCORE = 70.0

#: Placeholders the writer is instructed to emit for missing information.
#: Content inside them is a deliberate gap, not a hallucination.
PLACEHOLDER_PATTERN = re.compile(r"\[[^\]]*\]")

#: Document numbers such as "E-12345678-903-4567" or "2024/145".
DOCUMENT_NUMBER_PATTERN = re.compile(r"\b(?:[A-ZÇĞİÖŞÜ]-)?\d{2,}(?:[-/]\d+)+\b")

#: Dates in the formats the regulation uses.
DATE_PATTERN = re.compile(
    r"\b\d{1,2}[./]\d{1,2}[./]\d{4}\b"
    r"|\b\d{1,2}\s+(?:Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|"
    r"Eylül|Ekim|Kasım|Aralık)\s+\d{4}\b"
)

#: Legislation citations: "4982 sayılı", "madde 12", "m. 7/2".
LEGISLATION_PATTERN = re.compile(
    r"\b\d{3,5}\s+say[ıi]l[ıi]\b|\bmadde\s+\d+\b|\bm\.\s*\d+\b", re.IGNORECASE
)

#: Institution names ending in a recognisable public-body suffix.
INSTITUTION_PATTERN = re.compile(
    r"\b(?:[A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ]*\s+){1,5}"
    r"(?:Bakanlığı|Başkanlığı|Müdürlüğü|Müsteşarlığı|Müşavirliği|Genel Müdürlüğü|"
    r"Valiliği|Kaymakamlığı|Belediyesi|Daire Başkanlığı|Rektörlüğü|Dekanlığı)\b"
)

#: Monetary amounts.
AMOUNT_PATTERN = re.compile(
    r"\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?\s*(?:TL|₺|lira|Euro|EUR|USD|Dolar)\b",
    re.IGNORECASE,
)

#: Structural elements a well-formed official letter carries. Weighted because a
#: missing closing formula is a style defect while a missing subject line is a
#: regulatory one.
STRUCTURE_CHECKS: tuple[tuple[str, str, re.Pattern[str], float], ...] = (
    ("konu", "Konu satırı", re.compile(r"^\s*Konu\s*:", re.MULTILINE | re.IGNORECASE), 8.0),
    ("sayi", "Sayı satırı", re.compile(r"^\s*Sayı\s*:", re.MULTILINE | re.IGNORECASE), 6.0),
    ("tarih", "Tarih bilgisi", re.compile(r"Tarih\s*:|" + DATE_PATTERN.pattern, re.IGNORECASE), 4.0),
    (
        "kapanis",
        "Kapanış ifadesi (Arz/Rica ederim)",
        re.compile(r"(arz\s+ederim|rica\s+ederim|bilgilerinize\s+sunulur|arz\s+ve\s+rica)", re.IGNORECASE),
        8.0,
    ),
    (
        "imza",
        "İmza bloğu",
        re.compile(r"(e-?imzal[ıi]d[ıi]r|imza|müdür|başkan|bakan|amir|şef|uzman|müşavir)", re.IGNORECASE),
        4.0,
    ),
)

#: Penalty per ungrounded claim, and the ceiling on that penalty. Capped so a
#: draft with many small issues still scores above one that is structurally
#: broken -- the two failure modes should not collapse onto the same number.
UNSUPPORTED_CLAIM_PENALTY = 12.0
MAX_UNSUPPORTED_PENALTY = 60.0


class UnsupportedClaim(BaseModel):
    """A concrete assertion in the draft with no basis in the source material."""

    kind: str = Field(description="Bulgunun türü (ör. 'sayı', 'tarih', 'kurum').")
    value: str = Field(description="Taslakta geçen, kaynakta doğrulanamayan ifade.")
    explanation: str = Field(description="Bulgunun kısa Türkçe açıklaması.")


class VerificationReport(BaseModel):
    """Outcome of verifying a draft against its source material."""

    confidence_score: float = Field(
        ge=0.0, le=100.0, description="Taslağın kaynağa bağlılık ve yapı güven skoru."
    )
    requires_human_approval: bool = Field(
        description="Taslağın gönderilmeden önce insan onayı gerektirip gerektirmediği."
    )
    unsupported_claims: list[UnsupportedClaim] = Field(
        default_factory=list, description="Kaynakta doğrulanamayan ifadeler."
    )
    missing_structure: list[str] = Field(
        default_factory=list, description="Resmî yazıda eksik olan yapısal unsurlar."
    )
    placeholder_count: int = Field(
        default=0, description="Taslakta doldurulması gereken yer tutucu sayısı."
    )
    evaluation_notes: str = Field(
        default="", description="Skorun ve onay kararının kısa Türkçe gerekçesi."
    )


def _fold(text: str) -> str:
    """Normalize text for tolerant substring comparison.

    Args:
        text: Raw text.

    Returns:
        Lowercase ASCII with whitespace and punctuation collapsed, so that
        "E-12345678-903" matches "e 12345678 903" and casing or spacing
        differences between draft and source do not read as fabrication.
    """
    folded = unicodedata.normalize("NFKD", text or "")
    ascii_text = folded.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


def _strip_placeholders(text: str) -> str:
    """Remove ``[...]`` placeholders so their contents are not audited."""
    return PLACEHOLDER_PATTERN.sub(" ", text)


def _findall(pattern: re.Pattern[str], text: str) -> list[str]:
    """Return de-duplicated, whitespace-normalised matches for a pattern."""
    seen: dict[str, None] = {}
    for match in pattern.findall(text):
        value = (match if isinstance(match, str) else match[0]).strip()
        if value:
            seen.setdefault(re.sub(r"\s+", " ", value), None)
    return list(seen)


def _is_supported(value: str, haystack: str) -> bool:
    """Report whether a value appears in the reference material.

    Args:
        value: The claim as written in the draft.
        haystack: Folded concatenation of every trusted source.

    Returns:
        True when the value is grounded.
    """
    folded = _fold(value)
    if not folded:
        return True
    if folded in haystack:
        return True

    # Institution names survive minor rewording ("Çevre ve Şehircilik İl
    # Müdürlüğü" vs "İl Müdürlüğü"), so accept a strong token overlap rather
    # than demanding an exact span and flagging every legitimate paraphrase.
    tokens = [token for token in folded.split() if len(token) > 2]
    if len(tokens) >= 2:
        matched = sum(1 for token in tokens if token in haystack)
        if matched / len(tokens) >= 0.75:
            return True
    return False


def _collect_claims(draft: str, haystack: str) -> list[UnsupportedClaim]:
    """Find every concrete claim in the draft that the sources do not support.

    Args:
        draft: The generated draft, with placeholders already stripped.
        haystack: Folded concatenation of every trusted source.

    Returns:
        The unsupported claims, in document order by category.
    """
    checks: tuple[tuple[str, re.Pattern[str], str], ...] = (
        ("sayı", DOCUMENT_NUMBER_PATTERN, "Kaynak evrakta veya bağlamda geçmeyen bir belge sayısı."),
        ("tarih", DATE_PATTERN, "Kaynak evrakta veya bağlamda geçmeyen bir tarih."),
        ("mevzuat", LEGISLATION_PATTERN, "Doğrulanmış mevzuat bağlamında bulunmayan bir atıf."),
        ("kurum", INSTITUTION_PATTERN, "Kaynak evrakta veya bağlamda geçmeyen bir kurum adı."),
        ("tutar", AMOUNT_PATTERN, "Kaynak evrakta veya bağlamda geçmeyen bir parasal tutar."),
    )

    claims: list[UnsupportedClaim] = []
    for kind, pattern, explanation in checks:
        for value in _findall(pattern, draft):
            if not _is_supported(value, haystack):
                claims.append(
                    UnsupportedClaim(kind=kind, value=value, explanation=explanation)
                )
    return claims


def _check_structure(draft: str) -> tuple[list[str], float]:
    """Score the draft's structural completeness.

    Args:
        draft: The generated draft.

    Returns:
        The labels of missing elements and the total penalty incurred.
    """
    missing: list[str] = []
    penalty = 0.0
    for _key, label, pattern, weight in STRUCTURE_CHECKS:
        if not pattern.search(draft):
            missing.append(label)
            penalty += weight
    return missing, penalty


def _build_haystack(sources: Iterable[str]) -> str:
    """Fold every trusted source into one searchable string."""
    return _fold(" \n ".join(source for source in sources if source))


def verify_draft(
    draft: str,
    *,
    source_document: str = "",
    context: str = "",
    classification: dict[str, Any] | None = None,
    instructions: str = "",
    strict: bool = True,
) -> VerificationReport:
    """Verify a draft's groundedness and structural completeness.

    Args:
        draft: The generated draft text.
        source_document: The incoming document the draft responds to.
        context: Retrieved legislation excerpts.
        classification: Analysis output, whose extracted fields also count as
            trusted material.
        instructions: The user's instructions, which may legitimately introduce
            names or dates the source document does not contain.
        strict: When False (the ``other_official`` correspondence type, where the
            writer is permitted to supply conventional boilerplate) ungrounded
            claims are reported but do not force human approval.

    Returns:
        The verification report.
    """
    if not draft.strip():
        return VerificationReport(
            confidence_score=0.0,
            requires_human_approval=True,
            evaluation_notes="Taslak boş olduğu için doğrulanamadı.",
        )

    trusted: list[str] = [source_document, context, instructions]
    if classification:
        trusted.append(_flatten_classification(classification))
    haystack = _build_haystack(trusted)

    placeholder_count = len(PLACEHOLDER_PATTERN.findall(draft))
    auditable = _strip_placeholders(draft)

    claims = _collect_claims(auditable, haystack)
    missing_structure, structure_penalty = _check_structure(draft)

    claim_penalty = min(
        len(claims) * UNSUPPORTED_CLAIM_PENALTY, MAX_UNSUPPORTED_PENALTY
    )
    score = max(0.0, 100.0 - claim_penalty - structure_penalty)

    requires_approval = (
        score < MIN_AUTOMATED_CONFIDENCE_SCORE
        or bool(missing_structure)
        or placeholder_count > 0
        or (strict and bool(claims))
    )

    return VerificationReport(
        confidence_score=round(score, 1),
        requires_human_approval=requires_approval,
        unsupported_claims=claims,
        missing_structure=missing_structure,
        placeholder_count=placeholder_count,
        evaluation_notes=_build_notes(
            claims, missing_structure, placeholder_count, score
        ),
    )


def _flatten_classification(classification: dict[str, Any]) -> str:
    """Render analysis output as plain text for grounding comparisons.

    Args:
        classification: The analysis result.

    Returns:
        Every scalar value in the structure, space-joined.
    """
    parts: list[str] = []

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                _walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                _walk(item)
        elif hasattr(value, "page_content"):
            parts.append(str(value.page_content))
        elif hasattr(value, "model_dump"):
            _walk(value.model_dump())
        elif value is not None and not isinstance(value, bool):
            parts.append(str(value))

    _walk(classification)
    return " ".join(parts)


def _build_notes(
    claims: list[UnsupportedClaim],
    missing_structure: list[str],
    placeholder_count: int,
    score: float,
) -> str:
    """Compose the Turkish rationale shown alongside the score.

    Args:
        claims: Unsupported claims found.
        missing_structure: Missing structural elements.
        placeholder_count: Number of unfilled placeholders.
        score: The computed confidence score.

    Returns:
        A human-readable summary.
    """
    notes: list[str] = []
    if claims:
        sample = ", ".join(f"{claim.kind}: '{claim.value}'" for claim in claims[:3])
        notes.append(
            f"{len(claims)} adet kaynakta doğrulanamayan ifade tespit edildi ({sample})."
        )
    if missing_structure:
        notes.append(f"Eksik yapısal unsurlar: {', '.join(missing_structure)}.")
    if placeholder_count:
        notes.append(
            f"{placeholder_count} adet doldurulması gereken yer tutucu bulunuyor."
        )
    if not notes:
        notes.append(
            "Taslaktaki tüm somut bilgiler kaynak evrak ve mevzuat bağlamıyla "
            "doğrulandı; zorunlu yapısal unsurlar mevcut."
        )
    notes.append(f"Güven skoru: {score:.1f}/100.")
    return " ".join(notes)
