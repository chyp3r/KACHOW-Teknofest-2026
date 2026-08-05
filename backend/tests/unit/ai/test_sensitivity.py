"""Unit tests for the input-side sensitivity assessment."""

from dataclasses import replace

from app.ai.compliance.evrak_field import EvrakField
from app.ai.guardrails.sensitivity import assess
from app.ai.policy import get_policy
from app.core.enums.sensitivity_level import SensitivityLevel

VALID_TCKN = "12345678950"


def _fields(**overrides) -> EvrakField:
    return EvrakField(**overrides)


# ==========================================
# gizlilik_derecesi -> SensitivityLevel
# ==========================================
def test_no_marking_and_no_pii_is_unmarked_and_needs_no_review():
    result = assess(fields=_fields(), text="Sayın Makam, bilgilerinize arz ederim.")
    assert result.level is SensitivityLevel.UNMARKED
    assert result.requires_review is False
    assert result.pii_findings == []
    assert result.reasons == []


def test_gizli_marking_requires_review():
    result = assess(fields=_fields(gizlilik_derecesi="Gizli"), text="")
    assert result.level is SensitivityLevel.GIZLI
    assert result.requires_review is True
    assert any("gizlilik_derecesi" in reason for reason in result.reasons)


def test_cok_gizli_marking_requires_review():
    result = assess(fields=_fields(gizlilik_derecesi="ÇOK GİZLİ"), text="")
    assert result.level is SensitivityLevel.COK_GIZLI
    assert result.requires_review is True


def test_hizmete_ozel_marking_does_not_require_review():
    """Below the default policy's block threshold (Gizli/Çok Gizli) -- flagged
    via the level, not escalated to human review."""
    result = assess(fields=_fields(gizlilik_derecesi="Hizmete Özel"), text="")
    assert result.level is SensitivityLevel.HIZMETE_OZEL
    assert result.requires_review is False


def test_unrecognised_label_is_unmarked_not_a_guess():
    result = assess(fields=_fields(gizlilik_derecesi="Belirsiz Bir Not"), text="")
    assert result.level is SensitivityLevel.UNMARKED


def test_label_matching_folds_turkish_casing_and_diacritics():
    result = assess(fields=_fields(gizlilik_derecesi="gizli"), text="")
    assert result.level is SensitivityLevel.GIZLI


# ==========================================
# PII findings
# ==========================================
def test_pii_without_a_marking_flags_but_does_not_require_review():
    result = assess(
        fields=_fields(), text=f"T.C. Kimlik No: {VALID_TCKN}"
    )
    assert result.pii_findings
    assert result.requires_review is False
    assert any("pii bulgusu" in reason for reason in result.reasons)


def test_pii_below_the_confidence_floor_is_excluded():
    """A bare phone-shaped number scores below the default confidence floor
    -- noise, not a finding, per GuardrailPolicy.pii_confidence_floor."""
    policy = get_policy().guardrail
    result = assess(
        fields=_fields(),
        text="Sırada 0532 123 45 67 var.",
        policy=replace(policy, pii_confidence_floor=0.99),
    )
    assert result.pii_findings == []


def test_lowering_the_confidence_floor_surfaces_more_findings():
    policy = get_policy().guardrail
    result = assess(
        fields=_fields(),
        text="Sırada 0532 123 45 67 var.",
        policy=replace(policy, pii_confidence_floor=0.1),
    )
    assert result.pii_findings


# ==========================================
# Injection-scrub markers
# ==========================================
def test_scrub_markers_are_folded_into_reasons():
    result = assess(
        fields=_fields(), text="", scrub_markers=["olasi_talimat_enjeksiyonu_1_satir_kaldirildi"]
    )
    assert any("enjeksiyon" in reason for reason in result.reasons)


# ==========================================
# Combined
# ==========================================
def test_marking_and_pii_both_contribute_reasons():
    result = assess(
        fields=_fields(gizlilik_derecesi="Gizli"),
        text=f"T.C. Kimlik No: {VALID_TCKN}",
    )
    assert result.requires_review is True
    assert result.pii_findings
    assert len(result.reasons) >= 2
