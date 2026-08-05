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
from dataclasses import dataclass
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.ai.policy import get_policy
from app.ai.verification.normalizers import canonical_for_kind
from app.observability.ai_metrics import CLAIM_MATCH

logger = logging.getLogger(__name__)

#: Drafts scoring below this need a human before they can be sent.
#: Derived from the policy rather than duplicated, so the invariant tying it to
#: the routing threshold (see app.ai.policy.schema) cannot be violated by
#: editing one of the two numbers in isolation.
MIN_AUTOMATED_CONFIDENCE_SCORE = get_policy().verification.min_automated_confidence

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
#:
#: The lookbehind is load-bearing. Without it the pattern reads the tail of an
#: official document number as a law number -- "E-22222222-903-118 sayılı
#: yazınız" yields a phantom "118 sayılı" citation, which is then checked
#: against the legislation the draft actually cites and can be reported as a
#: fabricated reference on a perfectly grounded draft. Today that phantom is
#: absorbed by the token-overlap fallback only when some *other* "N sayılı"
#: citation happens to be in context; a draft whose context contains none would
#: have its own reference number flagged. Guarding against a preceding digit
#: also stops "12345 sayılı" from additionally matching as "2345 sayılı".
LEGISLATION_PATTERN = re.compile(
    r"(?<![-/\d])\b\d{3,5}\s+say[ıi]l[ıi]\b|\bmadde\s+\d+\b|\bm\.\s*\d+\b",
    re.IGNORECASE,
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
UNSUPPORTED_CLAIM_PENALTY = get_policy().verification.unsupported_claim_penalty
MAX_UNSUPPORTED_PENALTY = get_policy().verification.max_unsupported_penalty


#: How a claim was matched against the trusted sources, weakest last.
#: ``exact`` and ``normalized`` are substring hits, ``canonical`` is a
#: type-aware equality (see :mod:`app.ai.verification.normalizers`),
#: ``token_overlap`` is the tolerant fallback for names, ``none`` means the
#: claim is ungrounded.
MatchMethod = Literal["exact", "canonical", "token_overlap", "empty", "none"]


@dataclass(frozen=True)
class _Support:
    """The outcome of checking one claim against the trusted material."""

    supported: bool
    method: MatchMethod
    canonical: Optional[str] = None
    best_overlap: float = 0.0


class UnsupportedClaim(BaseModel):
    """A concrete assertion in the draft with no basis in the source material."""

    kind: str = Field(description="Bulgunun türü (ör. 'sayı', 'tarih', 'kurum').")
    value: str = Field(description="Taslakta geçen, kaynakta doğrulanamayan ifade.")
    explanation: str = Field(description="Bulgunun kısa Türkçe açıklaması.")
    canonical: str = Field(
        default="",
        description=(
            "İfadenin kaynakta aranan kanonik biçimi (ör. '2026-03-12'). Boşsa "
            "bu tür için kanonikleştirme yok ya da değer ayrıştırılamadı."
        ),
    )
    best_overlap: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Kaynakla en iyi jeton örtüşme oranı. Eşiğe ne kadar yaklaşıldığını "
            "gösterir; 0.0 hiçbir ortak jeton bulunamadığı anlamına gelir."
        ),
    )


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


#: Claim kinds, their extraction pattern and the Turkish explanation shown when
#: one turns out to be ungrounded. Module level so the canonical index and the
#: claim collector are guaranteed to iterate the same set of kinds.
CLAIM_CHECKS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("sayı", DOCUMENT_NUMBER_PATTERN, "Kaynak evrakta veya bağlamda geçmeyen bir belge sayısı."),
    ("tarih", DATE_PATTERN, "Kaynak evrakta veya bağlamda geçmeyen bir tarih."),
    ("mevzuat", LEGISLATION_PATTERN, "Doğrulanmış mevzuat bağlamında bulunmayan bir atıf."),
    ("kurum", INSTITUTION_PATTERN, "Kaynak evrakta veya bağlamda geçmeyen bir kurum adı."),
    ("tutar", AMOUNT_PATTERN, "Kaynak evrakta veya bağlamda geçmeyen bir parasal tutar."),
)

#: Minimum share of a value's significant tokens that must appear in the
#: sources for the tolerant fallback to accept it.
TOKEN_OVERLAP_THRESHOLD = get_policy().verification.token_overlap_threshold


def _build_canonical_index(raw_sources: str) -> dict[str, set[str]]:
    """Index every typed value in the trusted material by its canonical form.

    Built from the *raw* sources rather than the folded haystack: the extraction
    patterns are case-sensitive where it matters (``INSTITUTION_PATTERN``) and
    the textual date alternation matches "Mart", not "mart".

    Args:
        raw_sources: The trusted material, joined but not folded.

    Returns:
        Claim kind -> the set of canonical forms present in the sources.
    """
    index: dict[str, set[str]] = {}
    for kind, pattern, _explanation in CLAIM_CHECKS:
        forms: set[str] = set()
        for value in _findall(pattern, raw_sources):
            canonical = canonical_for_kind(kind, value)
            if canonical:
                forms.add(canonical)
        index[kind] = forms
    return index


def _token_overlap(folded: str, haystack: str) -> float:
    """Share of a value's significant tokens that appear in the sources.

    Args:
        folded: The folded claim value.
        haystack: Folded concatenation of every trusted source.

    Returns:
        The overlap in [0, 1]. Values with fewer than two significant tokens
        score 0.0 -- a single token either matched exactly or is not evidence.
    """
    tokens = [token for token in folded.split() if len(token) > 2]
    if len(tokens) < 2:
        return 0.0
    return sum(1 for token in tokens if token in haystack) / len(tokens)


def _support_for(
    kind: str, value: str, haystack: str, canonical_index: dict[str, set[str]]
) -> _Support:
    """Decide whether one claim is grounded, and record how.

    The ladder is ordered strongest first, and the canonical rung is what
    closes the gap this module's docstring describes: a date written
    "1 Mart 2026" against a source that says "01.03.2026" is the *same fact*,
    but no amount of substring or token comparison can see that.

    ``canonical`` is checked before ``token_overlap`` deliberately. For a typed
    value, canonical equality is exact and total -- if it matches, the value is
    grounded, and if it does not, a partial token overlap between two different
    dates is not evidence of anything.

    Args:
        kind: The claim kind.
        value: The claim as written in the draft.
        haystack: Folded concatenation of every trusted source.
        canonical_index: Canonical forms present in the sources, by kind.

    Returns:
        The support decision, the rung that produced it, and the evidence.
    """
    folded = _fold(value)
    if not folded:
        return _Support(supported=True, method="empty")

    if folded in haystack:
        return _Support(supported=True, method="exact")

    canonical = canonical_for_kind(kind, value)
    if canonical is not None and canonical in canonical_index.get(kind, set()):
        return _Support(supported=True, method="canonical", canonical=canonical)

    # Institution names survive minor rewording ("Çevre ve Şehircilik İl
    # Müdürlüğü" vs "İl Müdürlüğü"), so accept a strong token overlap rather
    # than demanding an exact span and flagging every legitimate paraphrase.
    overlap = _token_overlap(folded, haystack)
    if overlap >= TOKEN_OVERLAP_THRESHOLD:
        return _Support(
            supported=True, method="token_overlap", canonical=canonical, best_overlap=overlap
        )

    return _Support(
        supported=False, method="none", canonical=canonical, best_overlap=overlap
    )


def _collect_claims(
    draft: str, haystack: str, canonical_index: dict[str, set[str]]
) -> list[UnsupportedClaim]:
    """Find every concrete claim in the draft that the sources do not support.

    Args:
        draft: The generated draft, with placeholders already stripped.
        haystack: Folded concatenation of every trusted source.
        canonical_index: Canonical forms present in the sources, by kind.

    Returns:
        The unsupported claims, in document order by category, each carrying
        the canonical form that was searched for and how close the best textual
        match came.
    """
    claims: list[UnsupportedClaim] = []

    for kind, pattern, explanation in CLAIM_CHECKS:
        for value in _findall(pattern, draft):
            support = _support_for(kind, value, haystack, canonical_index)
            CLAIM_MATCH.labels(kind=kind, method=support.method).inc()

            if support.supported:
                continue

            claims.append(
                UnsupportedClaim(
                    kind=kind,
                    value=value,
                    explanation=explanation,
                    canonical=support.canonical or "",
                    best_overlap=round(support.best_overlap, 2),
                )
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

    # Two views of the same material: the folded one for substring comparison,
    # the raw one for the case-sensitive extraction patterns that feed the
    # canonical index.
    raw_sources = " \n ".join(source for source in trusted if source)
    haystack = _fold(raw_sources)
    canonical_index = _build_canonical_index(raw_sources)

    placeholder_count = len(PLACEHOLDER_PATTERN.findall(draft))
    auditable = _strip_placeholders(draft)

    claims = _collect_claims(auditable, haystack, canonical_index)
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


def check_groundedness(text: str, *, source_materials: str) -> list[UnsupportedClaim]:
    """Find claims in arbitrary text that ``source_materials`` doesn't support.

    Thin public wrapper around the same claim-extraction/matching pipeline
    ``verify_draft`` uses internally (fold the sources, index their
    canonical forms, strip placeholders, walk the claim patterns), for a
    caller that wants groundedness checking alone, without ``verify_draft``'s
    draft-specific structural scoring (closing-formula/imza-block checks that
    don't apply to a conversational reply). Currently used by
    ``app.ai.guardrails.output_gate`` to check assist replies against
    whatever tool results and cached document text backed this turn --
    reused, not reimplemented, so there is exactly one tuned set of claim
    patterns in the codebase.

    Args:
        text: The text to audit (e.g. a generated assist reply).
        source_materials: Trusted material the text should be grounded in.

    Returns:
        Every concrete claim in ``text`` with no basis in ``source_materials``.
    """
    haystack = _fold(source_materials)
    canonical_index = _build_canonical_index(source_materials)
    auditable = _strip_placeholders(text)
    return _collect_claims(auditable, haystack, canonical_index)


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
