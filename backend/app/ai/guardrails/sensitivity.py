"""Combine confidentiality marking, PII findings and injection markers into
one input-side sensitivity assessment.

Pure function over already-extracted data (``EvrakField``, PII findings,
injection-scrub markers) -- no I/O, no model call, unit-testable the same way
``app.ai.verification.draft_verifier.verify_draft`` is: given inputs, one
deterministic verdict.
"""

import unicodedata
from typing import Any, Optional, Sequence

from pydantic import BaseModel, Field

from app.ai.compliance.evrak_field import EvrakField
from app.ai.guardrails.pii import PiiFinding, find_pii
from app.ai.policy import GuardrailPolicy, get_policy
from app.core.enums.sensitivity_level import LABEL_ALIASES, SensitivityLevel

#: Same fold technique as ``app.ai.guardrails.injection._fold`` and
#: ``app.ai.verification.normalizers._fold`` -- each guardrail/verification
#: module owns its own copy rather than sharing a private helper across
#: module boundaries, matching this codebase's existing convention.
_TURKISH_MAP = str.maketrans(
    {
        "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i",
        "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
    }
)


def _fold(text: str) -> str:
    """Fold Turkish text to lowercase ASCII for label matching."""
    translated = (text or "").translate(_TURKISH_MAP)
    normalized = unicodedata.normalize("NFKD", translated)
    return normalized.encode("ascii", "ignore").decode("ascii").lower().strip()


def _level_from_label(label: Optional[str]) -> SensitivityLevel:
    """Map a free-text ``gizlilik_derecesi`` value onto ``SensitivityLevel``.

    Args:
        label: The raw value read off the document (e.g. "Hizmete Özel"), or
            None when the document carries no confidentiality marking.

    Returns:
        The matched level, or ``UNMARKED`` when the label is absent or does
        not match a known grade -- an unrecognised label is not evidence of
        anything, so it must not silently escalate.
    """
    if not label:
        return SensitivityLevel.UNMARKED
    return LABEL_ALIASES.get(_fold(label), SensitivityLevel.UNMARKED)


class SensitivityAssessment(BaseModel):
    """Input-side guardrail verdict for one document."""

    level: SensitivityLevel = Field(
        description=(
            "Belgeden çıkarılan HAM gizlilik derecesi -- belgede hiç damga "
            "yoksa UNMARKED, denetim izi için asla üzerine yazılmaz."
        )
    )
    effective_level: SensitivityLevel = Field(
        default=SensitivityLevel.UNMARKED,
        description=(
            "Erişim denetimi ve tüm diğer kararlarda fiilen kullanılan "
            "derece -- level UNMARKED ise policy.default_sensitivity_level'a "
            "otomatik atanır, aksi halde level ile aynıdır."
        ),
    )
    is_defaulted: bool = Field(
        default=False,
        description="effective_level, belgede hiç damga olmadığı için varsayılan atandıysa True.",
    )
    pii_findings: list[PiiFinding] = Field(default_factory=list)
    requires_review: bool = Field(
        description="Gizlilik derecesi (effective_level) politika eşiğini aşıyorsa True."
    )
    reasons: list[str] = Field(default_factory=list)


def assess(
    *,
    fields: EvrakField,
    text: str = "",
    scrub_markers: Sequence[str] = (),
    policy: Optional[GuardrailPolicy] = None,
) -> SensitivityAssessment:
    """Assess a document's sensitivity from its parsed fields and raw text.

    Args:
        fields: The document's extracted ``EvrakField`` (reads
            ``gizlilik_derecesi``).
        text: Extracted document text, scanned for PII patterns.
        scrub_markers: Injection-scrub markers already found by
            ``app.ai.guardrails.injection.scrub_extracted_text``, folded into
            the reasons list so one call site (``DocumentService``) has one
            place to log everything a document tripped.
        policy: Guardrail policy to gate against. Defaults to the process
            policy.

    Returns:
        The combined assessment. ``requires_review`` reflects only the
        confidentiality grade (per the resolved policy: a marked Gizli/Çok
        Gizli document routes to human review the same way a low-confidence
        draft does) -- PII alone flags without blocking, per the same policy.
    """
    active_policy = policy or get_policy().guardrail

    level = _level_from_label(fields.gizlilik_derecesi)
    is_defaulted = level is SensitivityLevel.UNMARKED
    effective_level = active_policy.default_sensitivity_level if is_defaulted else level
    findings = [
        finding
        for finding in find_pii(text)
        if finding.confidence >= active_policy.pii_confidence_floor
    ]

    reasons: list[str] = []
    if level is not SensitivityLevel.UNMARKED:
        reasons.append(f"gizlilik_derecesi: {fields.gizlilik_derecesi}")
    elif is_defaulted:
        reasons.append(
            "gizlilik derecesi belgede belirtilmemiş; en düşük dereceye "
            f"({effective_level.value}) otomatik atandı"
        )
    if findings:
        kinds = ", ".join(sorted({finding.kind for finding in findings}))
        reasons.append(f"{len(findings)} pii bulgusu ({kinds})")
    if scrub_markers:
        reasons.append(f"{len(scrub_markers)} enjeksiyon işareti temizlendi")

    requires_review = effective_level in active_policy.sensitivity_block_levels

    return SensitivityAssessment(
        level=level,
        effective_level=effective_level,
        is_defaulted=is_defaulted,
        pii_findings=findings,
        requires_review=requires_review,
        reasons=reasons,
    )


def assessment_from_analysis(analysis: dict[str, Any]) -> SensitivityAssessment:
    """Reconstruct a ``SensitivityAssessment`` from a classification dict.

    Two different shapes reach this function depending on which path
    ``planning_graph._run_classification`` took this turn: a live
    ``document_analysis_graph`` invocation carries the assessment under
    ``sensitivity_assessment`` with this module's own field names (``level``,
    ``requires_review``), while the cached path returns an assembled
    ``DocumentAnalysisResponseSchema`` dump, which carries the same
    information under ``guardrail`` with the API-facing schema's field names
    (``sensitivity_level``, ``requires_human_review``) -- see
    ``GuardrailAssessmentSchema`` in ``app.domains.documents.schema.
    document_schema``. Both are read here so callers (``_run_assist``,
    ``output_gate.evaluate_response``) don't have to know which path produced
    the dict they're holding.

    Args:
        analysis: A classification/analysis dict, in either shape above.

    Returns:
        The reconstructed assessment. Missing or unrecognised data degrades
        to an all-clear ``UNMARKED`` assessment rather than raising -- a
        malformed or absent assessment must never itself become the reason a
        response is blocked.
    """
    raw = analysis.get("guardrail") or analysis.get("sensitivity_assessment") or {}

    level_raw = raw.get("sensitivity_level", raw.get("level", SensitivityLevel.UNMARKED.value))
    try:
        level = SensitivityLevel(level_raw)
    except ValueError:
        level = SensitivityLevel.UNMARKED

    # Older cached analyses (written before effective_level existed) carry
    # no such key -- falls back to `level` itself, same as if the document
    # had never been defaulted, rather than raising or silently blocking.
    effective_level_raw = raw.get("effective_sensitivity_level", raw.get("effective_level"))
    try:
        effective_level = (
            SensitivityLevel(effective_level_raw) if effective_level_raw is not None else level
        )
    except ValueError:
        effective_level = level
    is_defaulted = bool(
        raw.get("sensitivity_is_defaulted", raw.get("is_defaulted", False))
    )

    pii_findings = [
        PiiFinding(**item) if isinstance(item, dict) else item
        for item in raw.get("pii_findings") or []
    ]
    requires_review = bool(raw.get("requires_human_review", raw.get("requires_review", False)))
    reasons = list(raw.get("reasons") or [])

    return SensitivityAssessment(
        level=level,
        effective_level=effective_level,
        is_defaulted=is_defaulted,
        pii_findings=pii_findings,
        requires_review=requires_review,
        reasons=reasons,
    )
