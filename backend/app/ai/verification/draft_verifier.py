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
from typing import Any, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from app.ai.policy import get_policy
from app.ai.verification.confidence_rules import AppliedRule, RuleFinding, score_findings
from app.ai.verification.normalizers import _TURKISH_MAP, canonical_for_kind
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

#: Structural elements a well-formed official letter carries. The penalty for
#: each lives in `confidence_rules.RULES` (see `_STRUCTURE_RULE_IDS` below),
#: not here -- this table stays purely detection (key/label/pattern), so
#: there is exactly one place a structural weight can be edited.
STRUCTURE_CHECKS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("konu", "Konu satırı", re.compile(r"^\s*Konu\s*:", re.MULTILINE | re.IGNORECASE)),
    ("sayi", "Sayı satırı", re.compile(r"^\s*Sayı\s*:", re.MULTILINE | re.IGNORECASE)),
    ("tarih", "Tarih bilgisi", re.compile(r"Tarih\s*:|" + DATE_PATTERN.pattern, re.IGNORECASE)),
    (
        "kapanis",
        "Kapanış ifadesi (Arz/Rica ederim)",
        re.compile(r"(arz\s+ederim|rica\s+ederim|bilgilerinize\s+sunulur|arz\s+ve\s+rica)", re.IGNORECASE),
    ),
    (
        "imza",
        "İmza bloğu",
        re.compile(r"(e-?imzal[ıi]d[ıi]r|imza|müdür|başkan|bakan|amir|şef|uzman|müşavir)", re.IGNORECASE),
    ),
)

#: `STRUCTURE_CHECKS` key -> the `confidence_rules.RULES` id it feeds.
_STRUCTURE_RULE_IDS: dict[str, str] = {
    "konu": "eksik_konu_satiri",
    "sayi": "eksik_sayi_satiri",
    "tarih": "eksik_tarih",
    "kapanis": "eksik_kapanis",
    "imza": "eksik_imza_blogu",
}


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
    example_leaks: list[UnsupportedClaim] = Field(
        default_factory=list,
        description=(
            "Taslakta geçen, kaynakta doğrulanamayan ve yalnızca üslup referans "
            "örneklerinde bulunan değerler -- writer/reviser'a örnekten somut bilgi "
            "kopyalamaması söylenmiş olsa da, bunun deterministik doğrulaması."
        ),
    )
    instruction_only_claims: list[UnsupportedClaim] = Field(
        default_factory=list,
        description=(
            "Taslakta geçen, kaynak evrakta veya mevzuat bağlamında doğrulanamayan "
            "ama kullanıcının revizyon talimatında geçen değerler. Skora ve onay "
            "kararına example_leaks gibi katılmazlar -- kullanıcının talimatı "
            "tanım gereği kabul edilir (bkz. modül dokümantasyonu) -- ancak "
            "app.ai.revision.conflict bu listeyi talimatın mevzuat/kaynakla "
            "çelişip çelişmediğini denetlemek için okur."
        ),
    )
    incoming_number_leaks: list[UnsupportedClaim] = Field(
        default_factory=list,
        description=(
            "Taslağın KENDİ Sayı: satırının, cevaplanan gelen evrakın sayısıyla "
            "aynı olduğu durumlar (bkz. _check_incoming_number_leak). Genel "
            "dayanaksız-iddia denetiminden ayrı: bu değer kaynakta (classification) "
            "gerçekten var ve o yüzden 'dayanaksız' değil -- sorun, doğru olması "
            "değil, taslağın bu satırında ASLA görünmemesi gerekmesidir."
        ),
    )
    placeholder_count: int = Field(
        default=0, description="Taslakta doldurulması gereken yer tutucu sayısı."
    )
    applied_rules: list[AppliedRule] = Field(
        default_factory=list,
        description=(
            "confidence_score'u üreten kural tablosu satırları (bkz. "
            "app.ai.verification.confidence_rules) -- yalnızca bu doğrulama "
            "geçişinin kendi bulguları; app.ai.verification.llm_judge.merge_verdicts "
            "PII/yazışma türü tahmini/mevzuat bağlamı yokluğu/yargıç bulgularından "
            "gelen ek satırları kendi combined_score'unu hesaplarken buna ekler."
        ),
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
    # Turkish letters are translated explicitly before NFKD, not left to it: "ı"
    # (U+0131, dotless i) has no NFKD decomposition, so ascii/ignore silently
    # deleted it -- 'Kadıköy Kaymakamlığı' folded to 'kadkoy kaymakamlg' while the
    # same institution written 'KADIKÖY KAYMAKAMLIĞI' (the all-caps Turkish
    # letterhead convention, and also what OCR of a scanned header yields) folded
    # to 'kadikoy kaymakamligi' -- two different strings for one institution. A
    # draft that copied the name straight off the source document's own
    # letterhead scored as fabricating it twice and lost 24 points. Same map and
    # same translate-before-NFKD order as every other Turkish-aware fold in this
    # codebase (see app.ai.compliance.checker.normalize_value).
    folded = (text or "").translate(_TURKISH_MAP)
    decomposed = unicodedata.normalize("NFKD", folded)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
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


#: The outgoing draft's own "Sayı:" header line -- deliberately the same
#: anchor `STRUCTURE_CHECKS`'s "sayi" entry uses (start of line), so this
#: only ever reads the response's own number field, never an "İlgi:" line
#: that legitimately quotes the incoming document's number.
_OWN_NUMBER_LINE_PATTERN = re.compile(r"^\s*Sayı\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE)

def _check_incoming_number_leak(
    draft: str, classification: dict[str, Any] | None
) -> list[UnsupportedClaim]:
    """Flag the draft's own Sayı: line if it echoes the incoming document's.

    A response's own case number is assigned by the *writing* institution's
    registry at send time -- it can never legitimately be the number of the
    document being replied to (see `writer.md`'s "GELEN EVRAKIN KİMLİK
    BİLGİLERİ" rule). This is deliberately separate from `_collect_claims`'s
    general groundedness check: the incoming number IS grounded (it is part
    of `classification`, which is folded into the trusted haystack), so the
    general check has no reason to flag it there -- being *true* does not
    make it *allowed in this line*. This checks that narrower, positional
    rule directly.

    Args:
        draft: The generated draft text, unstripped (placeholders and all --
            this only ever matches a literal "Sayı: <value>" line, so a
            correctly-left `[Belge Sayısı]` placeholder never matches).
        classification: Analysis output, whose extracted `fields.sayi` is
            the incoming document's own number.

    Returns:
        A single-item list carrying the leaked value, or empty.
    """
    fields = (classification or {}).get("fields") or {}
    if hasattr(fields, "model_dump"):
        fields = fields.model_dump()
    incoming_sayi = str(fields.get("sayi") or "").strip()
    if not incoming_sayi:
        return []

    incoming_canonical = canonical_for_kind("sayı", incoming_sayi)
    incoming_folded = _fold(incoming_sayi)

    for match in _OWN_NUMBER_LINE_PATTERN.finditer(draft):
        own_value = match.group(1).strip()
        if not _strip_placeholders(own_value).strip():
            continue  # a correctly-left placeholder, not a leak
        own_canonical = canonical_for_kind("sayı", own_value)
        same = _fold(own_value) == incoming_folded or (
            incoming_canonical is not None and own_canonical == incoming_canonical
        )
        if same:
            return [
                UnsupportedClaim(
                    kind="gelen_sayi_sizintisi",
                    value=own_value,
                    explanation=(
                        "Bu, taslağın KENDİ Sayı alanı -- ama değer, cevaplanan "
                        "gelen evrakın kendi sayısıyla aynı. Giden yazının sayısı "
                        "yazan kurumun evrak kaydınca verilir; gelen evrakın "
                        "sayısı yalnızca İlgi satırında kullanılabilir."
                    ),
                    canonical=own_canonical or "",
                )
            ]
    return []


#: Structure keys that don't apply to an individually-signed petition (an
#: itiraz/başvuru/şikayet dilekçesi, or any sub-genre resolving with
#: "dilekçe" in its label -- see ``resolve_correspondence_type``). A
#: petitioner never assigns their own case number, so requiring a "Sayı:"
#: line here would force the writer to fabricate one or fail verification on
#: every well-formed petition it produces. The other checks (Konu, Tarih,
#: kapanış, imza) still apply -- a petition has all of those, just not an
#: institutional case number.
PETITION_EXEMPT_STRUCTURE_KEYS = frozenset({"sayi"})


def _check_structure(
    draft: str, *, skip_keys: frozenset[str] = frozenset()
) -> tuple[list[str], list[RuleFinding]]:
    """Check the draft's structural completeness.

    Args:
        draft: The generated draft.
        skip_keys: Structure check keys to exempt (see
            ``PETITION_EXEMPT_STRUCTURE_KEYS``).

    Returns:
        The labels of missing elements, and one ``RuleFinding`` per missing
        element (see ``_STRUCTURE_RULE_IDS``) for ``score_findings`` to
        weigh -- this function no longer computes a penalty itself.
    """
    missing: list[str] = []
    findings: list[RuleFinding] = []
    for key, label, pattern in STRUCTURE_CHECKS:
        if key in skip_keys:
            continue
        if not pattern.search(draft):
            missing.append(label)
            findings.append(RuleFinding(rule_id=_STRUCTURE_RULE_IDS[key], detail=label))
    return missing, findings


def verify_draft(
    draft: str,
    *,
    source_document: str = "",
    context: str = "",
    classification: dict[str, Any] | None = None,
    instructions: str = "",
    strict: bool = True,
    style_examples: list[str] | None = None,
    is_individual_petition: bool = False,
    today: str = "",
    trusted_facts: Sequence[str] = (),
) -> VerificationReport:
    """Verify a draft's groundedness and structural completeness.

    Args:
        draft: The generated draft text.
        source_document: The incoming document the draft responds to.
        context: Retrieved legislation excerpts.
        today: The server-resolved date the draft's own "Tarih:" line was
            told to copy (see app.ai.workflows.dates.today_tr). Folded into
            the grounding haystack alongside source_document/context/
            classification, not treated as a hallucination the way any
            other date claim without a matching source value would be --
            this is the one date value that is legitimately injected
            rather than extracted.
        classification: Analysis output, whose extracted fields also count as
            trusted material.
        instructions: The user's instructions, which may legitimately introduce
            names or dates the source document does not contain. Not folded
            into the grounding haystack (see ``trusted`` below) -- a claim
            that traces only to the instructions is split into
            ``instruction_only_claims`` instead, so it still scores and
            approves exactly as if it were grounded (the user's word is
            trusted by construction, same net effect as before this field
            existed), but the fact that it came *only* from the instruction
            and not from the source/mevzuat becomes visible to
            ``app.ai.revision.conflict``, which is the layer responsible for
            deciding whether that is worth warning about.
        strict: When False (the ``other_official`` correspondence type, where the
            writer is permitted to supply conventional boilerplate) ungrounded
            claims are reported but do not force human approval.
        style_examples: Few-shot style-example texts handed to the writer (see
            ``ExampleRetriever``), if any. Any ungrounded claim that traces
            back to one of these -- a real institution name, date or case
            number the writer copied instead of treating the example as
            style-only -- is split out into ``example_leaks`` and always
            forces human approval, independent of ``strict``: a leaked real
            fact is a confidentiality/integrity problem the correspondence
            type's leniency was never meant to cover.
        is_individual_petition: True for a personal dilekçe-shaped sub-genre
            (see ``PETITION_EXEMPT_STRUCTURE_KEYS``) -- exempts the "Sayı:"
            structure check so a well-formed petition isn't flagged (and
            forced into a repair loop trying to add institutional scaffolding
            it should never have) for lacking a case number only the
            receiving institution assigns.
        trusted_facts: Values legitimately injected by the system rather
            than extracted from source_document/context -- today's own
            company identity fields (display name, letterhead, default
            signer title; see ``app.ai.identity.company_profile.
            CompanyProfile`` and ``draft_graph._build_brief``'s "KURUM
            KİMLİĞİ" section). Folded into the grounding haystack exactly
            like ``today`` is: without this, a company's own name would be
            flagged as an unsupported claim on every single draft that uses
            it.

    Returns:
        The verification report.
    """
    if not draft.strip():
        return VerificationReport(
            confidence_score=0.0,
            requires_human_approval=True,
            evaluation_notes="Taslak boş olduğu için doğrulanamadı.",
        )

    # `instructions` is deliberately not in the grounding haystack -- it is
    # split out below via `instruction_only_claims` instead of being folded
    # in here, so its presence is visible to the caller rather than silently
    # indistinguishable from source/mevzuat grounding.
    trusted: list[str] = [source_document, context, today, *trusted_facts]
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
    skip_keys = PETITION_EXEMPT_STRUCTURE_KEYS if is_individual_petition else frozenset()
    missing_structure, structure_findings = _check_structure(draft, skip_keys=skip_keys)

    # Split out claims that are unsupported by source/mevzuat but *are*
    # present in the user's own instructions -- checked before example_leaks
    # so a value the user explicitly typed is never mislabeled as a leaked
    # style example just because it happens to also appear in one. Kept out
    # of `claims`/the penalty and out of `requires_approval` on purpose: the
    # user's word is trusted by construction (see `verify_draft`'s
    # docstring), so this split changes *visibility*, not scoring.
    instruction_only_claims: list[UnsupportedClaim] = []
    instructions_haystack = _fold(instructions)
    if instructions_haystack:
        remaining_after_instructions: list[UnsupportedClaim] = []
        for claim in claims:
            if _fold(claim.value) in instructions_haystack:
                instruction_only_claims.append(
                    claim.model_copy(
                        update={
                            "explanation": (
                                "Bu değer kaynak evrakta veya mevzuat bağlamında değil, "
                                f"yalnızca kullanıcının talimatında geçiyor (özgün tür: {claim.kind})."
                            ),
                        }
                    )
                )
            else:
                remaining_after_instructions.append(claim)
        claims = remaining_after_instructions

    # Split out claims that are unsupported by the trusted sources *and*
    # traceable to a style example -- a stronger, more specific signal than
    # a generic unsupported claim (which could just as easily be an ordinary
    # model slip). Kept out of `claims`/repair_items on purpose: a repair
    # pass sees the exact same examples, so looping it back through the
    # reviser risks reproducing the same leak instead of fixing it (see
    # draft_graph.verify_node, which never feeds example_leaks into revision).
    example_leaks: list[UnsupportedClaim] = []
    examples_haystack = _fold(" \n ".join(style_examples or []))
    if examples_haystack:
        remaining: list[UnsupportedClaim] = []
        for claim in claims:
            if _fold(claim.value) in examples_haystack:
                example_leaks.append(
                    claim.model_copy(
                        update={
                            "kind": "ornek_sizintisi",
                            "explanation": (
                                "Bu değer yalnızca üslup referans örneğinde geçiyor; "
                                "kaynak evrakta, mevzuat bağlamında veya kullanıcı "
                                f"talimatında bulunmuyor (özgün tür: {claim.kind})."
                            ),
                        }
                    )
                )
            else:
                remaining.append(claim)
        claims = remaining

    incoming_number_leaks = _check_incoming_number_leak(draft, classification)

    # Every deterministic finding, in one list -- score_findings (the single
    # rule table, see app.ai.verification.confidence_rules) is the only
    # place a penalty number is computed from here on. `dayanaksiz_iddia`
    # is the one rule whose approval-forcing is conditional (`strict`) --
    # everything else uses the rule table's own unconditional default.
    findings: list[RuleFinding] = list(structure_findings)
    findings.extend(
        RuleFinding(
            rule_id="dayanaksiz_iddia",
            detail=f"{claim.kind}: {claim.value}",
            forces_approval=strict,
        )
        for claim in claims
    )
    findings.extend(
        RuleFinding(rule_id="ornek_sizintisi", detail=leak.value) for leak in example_leaks
    )
    findings.extend(
        RuleFinding(rule_id="gelen_sayi_sizintisi", detail=leak.value)
        for leak in incoming_number_leaks
    )
    findings.extend(
        RuleFinding(rule_id="doldurulmamis_yer_tutucu") for _ in range(placeholder_count)
    )

    outcome = score_findings(findings)
    score = outcome.score
    requires_approval = outcome.forces_approval or score < MIN_AUTOMATED_CONFIDENCE_SCORE

    return VerificationReport(
        confidence_score=score,
        requires_human_approval=requires_approval,
        unsupported_claims=claims,
        example_leaks=example_leaks,
        instruction_only_claims=instruction_only_claims,
        incoming_number_leaks=incoming_number_leaks,
        missing_structure=missing_structure,
        placeholder_count=placeholder_count,
        applied_rules=outcome.applied_rules,
        evaluation_notes=_build_notes(
            claims, missing_structure, placeholder_count, score, example_leaks,
            incoming_number_leaks,
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
    example_leaks: list[UnsupportedClaim] | None = None,
    incoming_number_leaks: list[UnsupportedClaim] | None = None,
) -> str:
    """Compose the Turkish rationale shown alongside the score.

    Args:
        claims: Unsupported claims found.
        missing_structure: Missing structural elements.
        placeholder_count: Number of unfilled placeholders.
        score: The computed confidence score.
        example_leaks: Unsupported claims traced back to a style example.
        incoming_number_leaks: The draft's own Sayı: line echoing the
            incoming document's number (see `_check_incoming_number_leak`).

    Returns:
        A human-readable summary.
    """
    notes: list[str] = []
    if incoming_number_leaks:
        notes.append(
            "Taslağın kendi Sayı: alanı, cevaplanan gelen evrakın sayısıyla "
            f"aynı ('{incoming_number_leaks[0].value}'); insan onayı gerekiyor."
        )
    if example_leaks:
        sample = ", ".join(f"'{claim.value}'" for claim in example_leaks[:3])
        notes.append(
            f"{len(example_leaks)} adet değer yalnızca üslup referans örneğinde "
            f"bulundu ve kaynakta doğrulanamadı ({sample}); insan onayı gerekiyor."
        )
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
