import logging
import re
import unicodedata
from typing import Any, Optional

from app.ai.compliance.evrak_field import ComplianceReport, EvrakField, MissingField
from app.ai.compliance.field_rule import (
    BLANK_VALUE_MARKER,
    REQUIRED_FIELD_RULES,
    RYUEHY,
    SEVERITY_ADVISORY,
    SEVERITY_REQUIRED,
    FieldRule,
)
from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.document_type import DocumentType

logger = logging.getLogger(__name__)

_TURKISH_FOLD = str.maketrans(
    {
        "ç": "c",
        "Ç": "c",
        "ğ": "g",
        "Ğ": "g",
        "ı": "i",
        "İ": "i",
        "ö": "o",
        "Ö": "o",
        "ş": "s",
        "Ş": "s",
        "ü": "u",
        "Ü": "u",
    }
)


def normalize_value(value: Any) -> str:
    """Fold a value to lower-case ASCII for deterministic marker comparison.

    Turkish characters are translated explicitly before Unicode normalisation
    because `str.lower()` maps "I" to "i" but leaves "İ" as a two-codepoint
    sequence, which would otherwise miss markers written with Turkish letters.

    Args:
        value: Any value; non-strings are stringified.

    Returns:
        The folded, whitespace-collapsed representation.
    """
    text = str(value).translate(_TURKISH_FOLD)
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


def is_blank(value: Any) -> bool:
    """Report whether a extracted field value counts as absent.

    Treats None, empty or whitespace-only strings, empty lists and the
    placeholder phrases in `BLANK_VALUE_MARKER` as absent. A language model asked
    for a missing field routinely answers "Belirtilmemiş" or "-" rather than null,
    and taking those at face value would report every document as complete.

    Args:
        value: The extracted field value.

    Returns:
        True when the value carries no information.
    """
    if value is None:
        return True
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return normalize_value(value) in BLANK_VALUE_MARKER


def _rules_for(document_type: DocumentType | str) -> tuple[FieldRule, ...]:
    """Resolve the rule set for a document type, falling back to OTHER.

    Args:
        document_type: The classified document type or its raw value.

    Returns:
        The applicable rules.
    """
    try:
        resolved = DocumentType(document_type)
    except ValueError:
        logger.warning(
            "Unknown document type %r; falling back to %s rules.",
            document_type,
            DocumentType.OTHER.value,
        )
        resolved = DocumentType.OTHER
    return REQUIRED_FIELD_RULES.get(
        resolved, REQUIRED_FIELD_RULES[DocumentType.OTHER]
    )


def check_required_fields(
    document_type: DocumentType | str,
    fields: EvrakField,
    is_signed: Optional[bool] = None,
) -> ComplianceReport:
    """Determine which required fields are missing from an extracted document.

    Pure set subtraction over a rule table — no language model is involved, so the
    result is byte-identical across runs and every citation is exact.

    Args:
        document_type: The classified type of the incoming document.
        fields: The fields extracted from the document.
        is_signed: Whether a signature-shaped ink mark was detected on the
            document (`app.infrastructure.extractors.marks.detect_marks`,
            threaded through `DocumentAnalysisState.detected_marks`). `None`
            when detection never ran (e.g. a born-digital PDF, which is
            never rasterised) — treated as unknown, not unsigned, matching
            this module's existing "never guess" posture (see `is_blank`'s
            own docstring). See the "İmza görseli" check below for what this
            actually gates.

    Returns:
        The missing fields with their legal basis and the overall status.
    """
    rules = _rules_for(document_type)
    missing: list[MissingField] = []

    for rule in rules:
        value = getattr(fields, rule.key, None)
        if is_blank(value):
            missing.append(
                MissingField(
                    key=rule.key,
                    label=rule.label,
                    severity=rule.severity,
                    mevzuat=rule.mevzuat,
                    reason=rule.reason,
                )
            )

    # Additive, and deliberately narrow: catches the gap the imza_sahibi rule
    # above cannot see. A *typed* name satisfies that rule (fields.imza_sahibi
    # non-blank) even when the page itself was never actually signed --
    # exactly the case a scanned, genuinely unsigned printout produces. Only
    # fires in that specific gap (name present, no detected mark); when
    # imza_sahibi is already blank the rule above already reports it, and
    # duplicating that here would be noise, not signal. Advisory, not
    # required: a heuristic detector's false negative (see marks.py's own
    # module docstring on why it is a review hint, not a legal determination)
    # must not, by itself, be able to mark an otherwise-complete document
    # "incomplete".
    if (
        is_signed is False
        and not is_blank(getattr(fields, "imza_sahibi", None))
        and any(rule.key == "imza_sahibi" for rule in rules)
    ):
        missing.append(
            MissingField(
                key="imza_gorseli",
                label="İmza görseli",
                severity=SEVERITY_ADVISORY,
                mevzuat=f"{RYUEHY} m.17",
                reason=(
                    "Belgede imza sahibinin adı yer alıyor ancak sayfada bir "
                    "imza taranmadı; belgenin gerçekten imzalanmış bir "
                    "nüshasının yüklendiğini doğrulayın."
                ),
            )
        )

    if not missing:
        status = ComplianceStatus.COMPLIANT
    elif any(item.severity == SEVERITY_REQUIRED for item in missing):
        status = ComplianceStatus.INCOMPLETE
    else:
        status = ComplianceStatus.PARTIALLY_COMPLIANT

    logger.info(
        "Compliance check for %s: %s (%d/%d field(s) missing).",
        document_type,
        status.value,
        len(missing),
        len(rules),
    )
    return ComplianceReport(
        status=status, missing_fields=missing, checked_field_count=len(rules)
    )
