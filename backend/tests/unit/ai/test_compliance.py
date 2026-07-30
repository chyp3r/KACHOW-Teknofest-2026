"""Unit tests for deterministic required-field (eksik bilgi) detection.

Deliberately mock-free: the whole point of doing this check in Python rather than
in the language model is that it is exactly reproducible and directly auditable.
"""

import json
import pathlib

import pytest

from app.ai.compliance import (
    BLANK_VALUE_MARKER,
    DOCUMENT_TYPE_LABELS,
    REQUIRED_FIELD_RULES,
    SEVERITY_ADVISORY,
    SEVERITY_REQUIRED,
    EvrakField,
    check_required_fields,
    detect_structural_signal,
    format_structural_signal,
    is_blank,
    normalize_value,
)
from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.document_type import DocumentType

COMPLETE_OFFICIAL_LETTER = EvrakField(
    sayi="E-12345678-903-4567",
    tarih="30.07.2026",
    konu="Yıllık İzin Talebi Hakkında",
    muhatap="İLGİLİ MAKAMA",
    gonderen_kurum="Örnek Bakanlığı",
    imza_sahibi="Mehmet Öztürk",
    imza_unvani="Genel Müdür",
)


# ==========================================
# Rule table integrity
# ==========================================
def test_every_document_type_has_rules():
    """Guards enum/table drift: a new type must not silently skip checking."""
    for document_type in DocumentType:
        assert document_type in REQUIRED_FIELD_RULES, document_type


def test_every_document_type_has_a_turkish_label():
    for document_type in DocumentType:
        assert DOCUMENT_TYPE_LABELS.get(document_type)


def test_every_rule_key_matches_an_evrak_field():
    """Guards typo'd keys, which would otherwise never fire."""
    valid_keys = set(EvrakField.model_fields)
    for document_type, rules in REQUIRED_FIELD_RULES.items():
        for rule in rules:
            assert rule.key in valid_keys, f"{document_type}: {rule.key}"


def test_every_rule_cites_legislation_and_gives_a_reason():
    for rules in REQUIRED_FIELD_RULES.values():
        for rule in rules:
            assert rule.mevzuat.strip()
            assert rule.reason.strip()
            assert rule.severity in (SEVERITY_REQUIRED, SEVERITY_ADVISORY)


def test_every_rule_set_has_at_least_one_mandatory_field():
    for document_type, rules in REQUIRED_FIELD_RULES.items():
        assert any(rule.severity == SEVERITY_REQUIRED for rule in rules), document_type


def test_official_letter_citations_use_verified_article_numbers():
    """Article numbers come from the official regulation text, not a paraphrase."""
    rules = {r.key: r.mevzuat for r in REQUIRED_FIELD_RULES[DocumentType.OFFICIAL_LETTER]}
    assert rules["sayi"].endswith("m.11")
    assert rules["tarih"].endswith("m.12")
    assert rules["konu"].endswith("m.13")
    assert rules["muhatap"].endswith("m.14")
    assert rules["gonderen_kurum"].endswith("m.10")
    assert rules["imza_sahibi"].endswith("m.17")


# ==========================================
# Turkish-aware blank detection
# ==========================================
def test_normalize_value_folds_turkish_characters():
    assert normalize_value("Belirtilmemiş") == "belirtilmemis"
    assert normalize_value("İSTANBUL") == "istanbul"
    assert normalize_value("ŞÇÖĞÜI") == "scogui"


@pytest.mark.parametrize(
    "value",
    [None, "", "   ", "-", "--", "Yok", "YOK", "belirtilmemiş", "Belirtilmemiş",
     "N/A", "n/a", "bilinmiyor", "Bulunmuyor", "null", "None", "Tespit edilemedi"],
)
def test_blank_markers_are_treated_as_absent(value):
    """A 9B model answers with these instead of null; taking them at face value
    would report every document as complete."""
    assert is_blank(value) is True


@pytest.mark.parametrize("value", ["E-123", "30.07.2026", "Ahmet Yılmaz", "0"])
def test_real_values_are_not_blank(value):
    assert is_blank(value) is False


def test_empty_and_populated_collections():
    assert is_blank([]) is True
    assert is_blank(["ilgi belgesi"]) is False


def test_blank_marker_set_is_prefolded():
    """Markers must already be in folded form or they can never match."""
    for marker in BLANK_VALUE_MARKER:
        assert normalize_value(marker) == marker


# ==========================================
# check_required_fields
# ==========================================
def test_complete_official_letter_is_compliant():
    report = check_required_fields(DocumentType.OFFICIAL_LETTER, COMPLETE_OFFICIAL_LETTER)
    assert report.status is ComplianceStatus.COMPLIANT
    assert report.missing_fields == []
    assert report.checked_field_count > 0


def test_missing_sayi_and_muhatap_are_detected_with_citations():
    fields = COMPLETE_OFFICIAL_LETTER.model_copy(update={"sayi": None, "muhatap": None})
    report = check_required_fields(DocumentType.OFFICIAL_LETTER, fields)

    assert report.status is ComplianceStatus.INCOMPLETE
    detected = {item.key: item for item in report.missing_fields}
    assert set(detected) == {"sayi", "muhatap"}
    assert detected["sayi"].mevzuat.endswith("m.11")
    assert detected["muhatap"].label == "Muhatap"


def test_blank_marker_values_count_as_missing():
    """The highest-value case: fields present in form but empty in substance."""
    fields = COMPLETE_OFFICIAL_LETTER.model_copy(
        update={"sayi": "Belirtilmemiş", "tarih": "-", "konu": "   "}
    )
    report = check_required_fields(DocumentType.OFFICIAL_LETTER, fields)

    assert report.status is ComplianceStatus.INCOMPLETE
    assert {item.key for item in report.missing_fields} == {"sayi", "tarih", "konu"}


def test_only_advisory_missing_yields_partially_compliant():
    fields = COMPLETE_OFFICIAL_LETTER.model_copy(update={"imza_unvani": None})
    report = check_required_fields(DocumentType.OFFICIAL_LETTER, fields)

    assert report.status is ComplianceStatus.PARTIALLY_COMPLIANT
    assert [item.key for item in report.missing_fields] == ["imza_unvani"]


def test_petition_uses_law_3071_rules():
    fields = EvrakField(konu="Bilgi talebi", basvuran_adi="Ayşe Demir")
    report = check_required_fields(DocumentType.PETITION, fields)

    detected = {item.key: item.mevzuat for item in report.missing_fields}
    assert "imza_sahibi" in detected
    assert "adres" in detected
    assert "3071" in detected["adres"]


def test_information_request_uses_law_4982_rules():
    report = check_required_fields(DocumentType.INFORMATION_REQUEST, EvrakField())
    citations = " ".join(item.mevzuat for item in report.missing_fields)
    assert "4982" in citations


def test_unknown_document_type_falls_back_to_other_rules():
    report = check_required_fields("bilinmeyen_tur", EvrakField())
    assert report.status is ComplianceStatus.INCOMPLETE
    assert report.checked_field_count == len(REQUIRED_FIELD_RULES[DocumentType.OTHER])


def test_raw_string_document_type_is_accepted():
    report = check_required_fields("official_letter", COMPLETE_OFFICIAL_LETTER)
    assert report.status is ComplianceStatus.COMPLIANT


def test_check_is_deterministic_across_repeated_calls():
    """Reproducibility is a scored criterion; the same input must never drift."""
    fields = COMPLETE_OFFICIAL_LETTER.model_copy(update={"sayi": None, "konu": "-"})
    runs = [
        [m.key for m in check_required_fields(DocumentType.OFFICIAL_LETTER, fields).missing_fields]
        for _ in range(5)
    ]
    assert all(run == runs[0] for run in runs)


def test_empty_document_reports_every_mandatory_field():
    report = check_required_fields(DocumentType.OFFICIAL_LETTER, EvrakField())
    mandatory = [
        r.key
        for r in REQUIRED_FIELD_RULES[DocumentType.OFFICIAL_LETTER]
        if r.severity == SEVERITY_REQUIRED
    ]
    detected = {item.key for item in report.missing_fields}
    assert set(mandatory).issubset(detected)


# ==========================================
# Dataset-driven regression over datasets/sample/
# ==========================================
# Makes the synthetic corpus a real test asset rather than demo decoration: the
# committed ground truth is checked against the rule table on every run, with no
# language model involved.
def _find_sample_dir() -> pathlib.Path:
    """Locate datasets/sample by walking up from this test file.

    Walked rather than hard-coded because the suite runs both from `backend/` on a
    workstation and from `/workspace` inside the container, where the repository
    root sits at a different depth.

    Returns:
        Path to the sample dataset directory (which may not exist).
    """
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "datasets" / "sample"
        if candidate.is_dir():
            return candidate
    return here.parents[4] / "datasets" / "sample"


SAMPLE_DIR = _find_sample_dir()
SAMPLE_FILES = sorted(SAMPLE_DIR.glob("evrak_*.json"))


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def test_sample_dataset_is_present():
    assert SAMPLE_FILES, f"No ground-truth files found in {SAMPLE_DIR}"


@pytest.mark.parametrize("path", SAMPLE_FILES, ids=lambda p: p.stem)
def test_sample_ground_truth_matches_the_rule_table(path):
    truth = _load(path)
    report = check_required_fields(
        truth["document_type"], EvrakField(**truth["expected_fields"])
    )
    detected = sorted(item.key for item in report.missing_fields)
    assert detected == truth["expected_missing_fields"], (
        f"{truth['id']}: expected {truth['expected_missing_fields']}, got {detected}"
    )


@pytest.mark.parametrize("path", SAMPLE_FILES, ids=lambda p: p.stem)
def test_sample_status_follows_from_missing_severities(path):
    truth = _load(path)
    report = check_required_fields(
        truth["document_type"], EvrakField(**truth["expected_fields"])
    )
    if not truth["expected_missing_fields"]:
        assert report.status is ComplianceStatus.COMPLIANT
    else:
        assert report.status in (
            ComplianceStatus.INCOMPLETE,
            ComplianceStatus.PARTIALLY_COMPLIANT,
        )


@pytest.mark.parametrize("path", SAMPLE_FILES, ids=lambda p: p.stem)
def test_sample_has_a_matching_text_file(path):
    assert path.with_suffix(".txt").is_file()


@pytest.mark.parametrize("path", SAMPLE_FILES, ids=lambda p: p.stem)
def test_sample_document_type_is_a_known_enum_member(path):
    truth = _load(path)
    assert DocumentType(truth["document_type"])


@pytest.mark.parametrize("path", SAMPLE_FILES, ids=lambda p: p.stem)
def test_sample_expected_fields_match_the_schema(path):
    """Guards typos in hand-authored ground truth."""
    truth = _load(path)
    unknown = set(truth["expected_fields"]) - set(EvrakField.model_fields)
    assert not unknown, f"{truth['id']}: unknown field(s) {unknown}"


def test_sample_dataset_covers_the_advisory_only_path():
    """At least one sample must yield PARTIALLY_COMPLIANT, or that branch is untested."""
    statuses = []
    for path in SAMPLE_FILES:
        truth = _load(path)
        statuses.append(
            check_required_fields(
                truth["document_type"], EvrakField(**truth["expected_fields"])
            ).status
        )
    assert ComplianceStatus.PARTIALLY_COMPLIANT in statuses
    assert ComplianceStatus.COMPLIANT in statuses
    assert ComplianceStatus.INCOMPLETE in statuses


def test_sample_dataset_contains_a_scanned_case():
    """The OCR path needs at least one image-only document."""
    assert any(_load(path).get("scanned") for path in SAMPLE_FILES)


# ==========================================
# Structural signals (deterministic classification prior)
# ==========================================
OFFICIAL_LETTER_TEXT = """T.C.
ÖRNEK BAKANLIĞI

Sayı : E-111-1
Tarih : 30.07.2026
Konu : Deneme

ÖRNEK VALİLİĞİNE

İlgi : 01.07.2026 tarihli yazınız.

Metin.

Ahmet Yılmaz
Genel Müdür"""

PETITION_TEXT = """ÖRNEK BELEDİYE BAŞKANLIĞINA

Tarih : 30.07.2026
Konu : Talep

Metin.

Ayşe Demir
Adres : Örnek Mah. No:1
İmza"""


def test_signal_detects_institutional_markers():
    signal = detect_structural_signal(OFFICIAL_LETTER_TEXT)
    assert signal.has_institution_header is True
    assert signal.has_sayi_field is True
    assert signal.has_ilgi_field is True
    assert signal.has_titled_signature is True
    assert signal.looks_institutional is True


def test_signal_does_not_treat_an_addressee_as_a_signature():
    """'BELEDİYE BAŞKANLIĞINA' is the addressee; reporting it as a titled
    signature would feed the classifier a false observation."""
    signal = detect_structural_signal(PETITION_TEXT)
    assert signal.has_titled_signature is False
    assert signal.has_institution_header is False
    assert signal.looks_institutional is False


def test_signal_detects_applicant_contact_block():
    assert detect_structural_signal(PETITION_TEXT).has_applicant_contact is True
    assert detect_structural_signal(OFFICIAL_LETTER_TEXT).has_applicant_contact is False


def test_signal_requires_more_than_a_header_to_look_institutional():
    signal = detect_structural_signal("T.C.\n\nrastgele metin")
    assert signal.has_institution_header is True
    assert signal.looks_institutional is False


def test_signal_ignores_sayi_appearing_mid_sentence():
    signal = detect_structural_signal("Bu yazıda sayı bilgisi bulunmamaktadır.")
    assert signal.has_sayi_field is False


def test_format_signal_states_the_institutional_conclusion():
    text = format_structural_signal(detect_structural_signal(OFFICIAL_LETTER_TEXT))
    assert "kurum anteti" in text
    assert "vatandaş başvurusu" in text


def test_format_signal_is_empty_when_nothing_is_detected():
    assert format_structural_signal(detect_structural_signal("düz metin")) == ""


@pytest.mark.parametrize("path", SAMPLE_FILES, ids=lambda p: p.stem)
def test_institutional_signal_matches_the_sample_document_type(path):
    """The load-bearing signal must agree with ground truth on every sample."""
    truth = _load(path)
    text = path.with_suffix(".txt").read_text(encoding="utf-8")
    institutional_types = {
        DocumentType.OFFICIAL_LETTER,
        DocumentType.CIRCULAR,
        DocumentType.DIRECTIVE,
    }
    expected = DocumentType(truth["document_type"]) in institutional_types
    assert detect_structural_signal(text).looks_institutional is expected
