"""Unit tests for deterministic parsing of prescribed header fields.

Mock-free by design: the regulation specifies these labels, so reading them needs
no model and the result must be exactly reproducible.
"""

import json
import pathlib

import pytest

from app.ai.compliance import EvrakField, is_blank
from app.ai.compliance.field_parser import (
    AUTHORITATIVE_FIELD,
    format_parsed_fields,
    merge_parsed_over_model,
    parse_labelled_fields,
)

OFFICIAL_LETTER = """T.C.
ÖRNEK BAKANLIĞI
Personel Genel Müdürlüğü

Sayı : E-11111111-903.07.02-4752
Tarih : 12.03.2026
Konu : Yıllık İzin Talebinin Değerlendirilmesi

ÖRNEK VALİLİĞİNE

İlgi : 01.03.2026 tarihli ve E-222-118 sayılı yazınız.

Metin.

Ahmet Yılmaz
Genel Müdür"""


def _find_sample_dir() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "datasets" / "sample"
        if candidate.is_dir():
            return candidate
    return here.parents[4] / "datasets" / "sample"


SAMPLE_DIR = _find_sample_dir()
SAMPLE_FILES = sorted(SAMPLE_DIR.glob("evrak_*.json"))

LABELLED_FIELDS = (
    "sayi",
    "tarih",
    "konu",
    "ilgi",
    "ekler",
    "adres",
    "gizlilik_derecesi",
    "ivedilik",
)


def test_parses_the_standard_header_block():
    parsed = parse_labelled_fields(OFFICIAL_LETTER)
    assert parsed["sayi"] == "E-11111111-903.07.02-4752"
    assert parsed["tarih"] == "12.03.2026"
    assert parsed["konu"] == "Yıllık İzin Talebinin Değerlendirilmesi"
    assert parsed["ilgi"] == ["01.03.2026 tarihli ve E-222-118 sayılı yazınız."]


def test_sayi_and_tarih_may_share_one_line():
    """The regulation puts Tarih at the right of the Sayı line (m.12)."""
    parsed = parse_labelled_fields("Sayı : E-1-2-3    Tarih : 12.03.2026")
    assert parsed["sayi"] == "E-1-2-3"
    assert parsed["tarih"] == "12.03.2026"


def test_empty_label_does_not_capture_the_following_line():
    """A blank 'Konu :' must yield nothing, not the next line's text."""
    parsed = parse_labelled_fields("Konu :\n\nÖRNEK MÜDÜRLÜĞÜNE\n")
    assert "konu" not in parsed


def test_blank_marker_values_are_parsed_verbatim():
    """Detecting them as blank is the checker's job, not the parser's."""
    parsed = parse_labelled_fields("Sayı : Belirtilmemiş\nTarih : -\n")
    assert parsed["sayi"] == "Belirtilmemiş"
    assert parsed["tarih"] == "-"
    assert is_blank(parsed["sayi"]) is True


def test_enumerated_ilgi_is_split_into_items():
    parsed = parse_labelled_fields(
        "İlgi : a) 01.01.2026 tarihli yazı b) 02.02.2026 tarihli yazı"
    )
    assert parsed["ilgi"] == ["01.01.2026 tarihli yazı", "02.02.2026 tarihli yazı"]


def test_absent_labels_produce_no_entries():
    assert parse_labelled_fields("Serbest metin, hiçbir etiket yok.") == {}


def test_whitespace_is_collapsed():
    parsed = parse_labelled_fields("Konu :   Çok    boşluklu   konu")
    assert parsed["konu"] == "Çok boşluklu konu"


def test_parser_is_deterministic():
    runs = [parse_labelled_fields(OFFICIAL_LETTER) for _ in range(5)]
    assert all(run == runs[0] for run in runs)


def test_merge_lets_parsed_values_win():
    merged = merge_parsed_over_model(
        {"sayi": "model uydurmasi", "iletisim": "0500 000 00 00"},
        {"sayi": "E-1-2-3"},
    )
    assert merged["sayi"] == "E-1-2-3"
    # Non-authoritative fields survive untouched: the parser cannot rule them out.
    assert merged["iletisim"] == "0500 000 00 00"


def test_format_parsed_fields_lists_resolved_names():
    note = format_parsed_fields({"sayi": "E-1", "tarih": "01.01.2026"})
    assert "sayi" in note and "tarih" in note


def test_format_parsed_fields_is_empty_when_nothing_parsed():
    assert format_parsed_fields({}) == ""


# ==========================================
# Dataset-driven: the accuracy claim, enforced
# ==========================================
@pytest.mark.parametrize("path", SAMPLE_FILES, ids=lambda p: p.stem)
def test_parser_recovers_every_labelled_field_in_the_corpus(path):
    with open(path, encoding="utf-8") as handle:
        truth = json.load(handle)
    text = path.with_suffix(".txt").read_text(encoding="utf-8")
    parsed = parse_labelled_fields(text)

    expected = {
        name
        for name in LABELLED_FIELDS
        if not is_blank(truth["expected_fields"].get(name))
    }
    recovered = {name for name in expected if not is_blank(parsed.get(name))}
    assert recovered == expected, f"{truth['id']}: kayıp {expected - recovered}"


@pytest.mark.parametrize("path", SAMPLE_FILES, ids=lambda p: p.stem)
def test_parser_never_invents_a_value(path):
    """A parsed value where ground truth has none would mask a real omission."""
    with open(path, encoding="utf-8") as handle:
        truth = json.load(handle)
    text = path.with_suffix(".txt").read_text(encoding="utf-8")
    parsed = parse_labelled_fields(text)

    invented = [
        name
        for name, value in parsed.items()
        if is_blank(truth["expected_fields"].get(name)) and not is_blank(value)
    ]
    assert invented == [], f"{truth['id']}: uydurulan alan {invented}"


# ==========================================
# Positional fields (m.10 başlık, m.14 muhatap, m.17 imza)
# ==========================================
POSITIONAL_FIELDS = ("gonderen_kurum", "muhatap", "imza_sahibi", "imza_unvani")

UNSIGNED_PETITION = """ÖRNEK KAYMAKAMLIĞINA

Tarih : 09.04.2026
Konu : Talep

Konunun ilgili birime iletilmesini talep ederim.

Ali Vural"""


def test_parses_letterhead_between_tc_and_first_heading():
    parsed = parse_labelled_fields(OFFICIAL_LETTER)
    assert parsed["gonderen_kurum"] == "ÖRNEK BAKANLIĞI Personel Genel Müdürlüğü"


def test_parses_addressee_by_dative_suffix():
    parsed = parse_labelled_fields(OFFICIAL_LETTER)
    assert parsed["muhatap"] == "ÖRNEK VALİLİĞİNE"


def test_parses_signature_name_and_title():
    parsed = parse_labelled_fields(OFFICIAL_LETTER)
    assert parsed["imza_sahibi"] == "Ahmet Yılmaz"
    assert parsed["imza_unvani"] == "Genel Müdür"


def test_a_bare_trailing_name_is_not_treated_as_a_signature():
    """An unsigned petition ends with the applicant's name. Claiming it as a
    signature would mask a genuine 3071 m.4 omission."""
    parsed = parse_labelled_fields(UNSIGNED_PETITION)
    assert "imza_sahibi" not in parsed
    assert parsed["muhatap"] == "ÖRNEK KAYMAKAMLIĞINA"


def test_explicit_imza_marker_corroborates_a_signature():
    """Turkish casing: 'İmza'.lower() is not 'imza', so folding must be used."""
    text = UNSIGNED_PETITION + "\nAdres : Örnek Mah. No:1\nİmza"
    parsed = parse_labelled_fields(text)
    assert parsed["imza_sahibi"] == "Ali Vural"


def test_letterhead_corroborates_a_signature_without_a_title():
    """An official letter is signed by definition (m.17)."""
    text = "T.C.\nÖRNEK BAKANLIĞI\n\nKonu : Deneme\n\nMetin arz ederim.\n\nMustafa Şahin"
    parsed = parse_labelled_fields(text)
    assert parsed["imza_sahibi"] == "Mustafa Şahin"
    assert "imza_unvani" not in parsed


def test_labelled_values_win_over_positional_guesses():
    text = "T.C.\nÖRNEK BAKANLIĞI\nAdres : Gerçek Adres 1\n\nMetin."
    parsed = parse_labelled_fields(text)
    assert parsed["adres"] == "Gerçek Adres 1"


@pytest.mark.parametrize("path", SAMPLE_FILES, ids=lambda p: p.stem)
def test_parser_recovers_positional_fields_across_the_corpus(path):
    with open(path, encoding="utf-8") as handle:
        truth = json.load(handle)
    text = path.with_suffix(".txt").read_text(encoding="utf-8")
    parsed = parse_labelled_fields(text)

    expected = {
        name
        for name in POSITIONAL_FIELDS
        if not is_blank(truth["expected_fields"].get(name))
    }
    recovered = {name for name in expected if not is_blank(parsed.get(name))}
    assert recovered == expected, f"{truth['id']}: kayıp {expected - recovered}"


# ==========================================
# Parser authority in both directions
# ==========================================
def test_model_value_is_discarded_for_an_unparsed_authoritative_field():
    """The regulation prescribes how `muhatap` appears; if the parser finds no
    such line the field is genuinely absent, and a model value for it would hide
    a real omission."""
    merged = merge_parsed_over_model({"muhatap": "İLGİLİ MAKAMA"}, {})
    assert merged["muhatap"] is None


def test_model_value_is_kept_for_a_non_authoritative_field():
    """An unlabelled address is common in petitions, so an absent parse means
    'unknown' rather than 'absent'."""
    merged = merge_parsed_over_model({"adres": "Örnek Mah. No:1"}, {})
    assert merged["adres"] == "Örnek Mah. No:1"


def test_unparsed_authoritative_list_field_becomes_empty_not_none():
    merged = merge_parsed_over_model({"ilgi": ["uydurma atıf"]}, {})
    assert merged["ilgi"] == []


def test_parsed_value_still_wins_over_the_model():
    merged = merge_parsed_over_model({"sayi": "UYDURMA"}, {"sayi": "E-1-2-3"})
    assert merged["sayi"] == "E-1-2-3"


def test_authoritative_set_only_contains_real_evrak_fields():
    assert AUTHORITATIVE_FIELD <= set(EvrakField.model_fields)


def test_fields_without_parser_support_are_not_authoritative():
    """Suppressing these would turn invented values into missing ones."""
    for name in ("adres", "iletisim", "gizlilik_derecesi", "ivedilik", "basvuran_adi"):
        assert name not in AUTHORITATIVE_FIELD


def test_unsigned_petition_signature_is_not_resurrected_by_the_model():
    """End-to-end guard for the 3071 m.4 case: parser refuses the bare trailing
    name, and the model must not put it back."""
    parsed = parse_labelled_fields(UNSIGNED_PETITION)
    merged = merge_parsed_over_model({"imza_sahibi": "Ali Vural"}, parsed)
    assert merged["imza_sahibi"] is None
