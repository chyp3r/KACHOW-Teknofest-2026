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
    HEADER_FIELD,
    count_header_fields,
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


# ==========================================
# ALL-CAPS surname (real official-correspondence convention, missed on 17/23
# hand-labelled real documents before this fix -- datasets/sample/'s
# synthetic corpus is uniformly Titlecase-only and never exercised this)
# ==========================================
def test_signature_with_all_caps_surname_is_recognised():
    """Turkish official correspondence conventionally sets the surname in
    full capitals ("Yaşar GÜLER"), not Titlecase ("Ahmet Yılmaz") -- the
    original pattern only accepted the latter."""
    text = "T.C.\nÖRNEK BAKANLIĞI\n\nKonu : Deneme\n\nMetin arz ederim.\n\nYaşar GÜLER\nBakan"
    parsed = parse_labelled_fields(text)
    assert parsed["imza_sahibi"] == "Yaşar GÜLER"
    assert parsed["imza_unvani"] == "Bakan"


def test_signature_with_titled_prefix_and_all_caps_surname_is_recognised():
    text = "T.C.\nÖRNEK BAKANLIĞI\n\nKonu : Deneme\n\nMetin arz ederim.\n\nProf. Dr. Ömer BOLAT\nBakan"
    parsed = parse_labelled_fields(text)
    assert parsed["imza_sahibi"] == "Prof. Dr. Ömer BOLAT"


def test_institution_name_is_never_mistaken_for_a_signature():
    """A Titlecase-worded institution mention ("Türkiye Büyük Millet
    Meclisi") is name-shaped by the same pattern that matches a person's
    name -- real regression: this line used to win over the actual
    signature line below it when the actual signer's ALL-CAPS surname
    didn't match the old pattern at all. Now that it does, the loop must
    still pick the real name first, not the institution line."""
    text = (
        "Sayı : Z-1\nTarih : 20.04.2026\n\nSAYIN VALİLİĞİNE\n\n"
        "Metin metin.\nRica ederim.\n\n"
        "Bekir BOZDAĞ\nTürkiye Büyük Millet Meclisi\nBaşkanvekili"
    )
    parsed = parse_labelled_fields(text)
    assert parsed["imza_sahibi"] == "Bekir BOZDAĞ"
    assert parsed["imza_unvani"] == "Başkanvekili"


def test_all_caps_institution_line_alone_never_matches_person_name():
    from app.ai.compliance.field_parser import _PERSON_NAME_LINE

    assert not _PERSON_NAME_LINE.match("TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞI")
    assert not _PERSON_NAME_LINE.match("MİLLÎ SAVUNMA BAKANLIĞI")


# ==========================================
# Evidence-based rescue (merge_parsed_over_model's document_text argument)
# ==========================================
def test_rescues_a_model_value_the_parser_structurally_cannot_reach():
    """`muhatap` (m.14) is only recovered positionally when the addressee is
    a dative-suffixed institution -- a named person ("Sayın Ceylan AKÇA
    CUPOLO") is structurally unreachable by that heuristic, but the model
    reads it correctly. Measured live against 4 real documents: the parser
    missed this exact shape on every one, and the model had the right
    answer every time."""
    doc = (
        "Sayı : Z-1\nTarih : 20.04.2026\n\n"
        "Sayın Ceylan AKÇA CUPOLO\nDiyarbakır Milletvekili\n\n"
        "Metin metin.\nRica ederim.\n\nBekir BOZDAĞ\nBaşkanvekili"
    )
    parsed = parse_labelled_fields(doc)
    assert "muhatap" not in parsed  # confirms this is genuinely the parser's blind spot
    merged = merge_parsed_over_model(
        {"muhatap": "Sayın Ceylan AKÇA CUPOLO"}, parsed, document_text=doc
    )
    assert merged["muhatap"] == "Sayın Ceylan AKÇA CUPOLO"


def test_ungrounded_model_value_is_still_discarded_with_document_text():
    """The original fabrication case ("İLGİLİ MAKAMA" invented for a letter
    with no addressee at all) must still be caught: the value simply never
    appears in the document, grounded or not."""
    doc = "T.C.\nÖRNEK BAKANLIĞI\n\nKonu : Bir şey\n\nMetin metin metin.\n\nAhmet YILMAZ\nMüdür"
    merged = merge_parsed_over_model({"muhatap": "İLGİLİ MAKAMA"}, {}, document_text=doc)
    assert merged["muhatap"] is None


def test_reordered_model_value_is_rescued_via_token_overlap():
    """Real live case, measured against qwen3.5:9b on CY-033: the model
    reported `muhatap` as "Ankara Milletvekili İdris ŞAHİN", but the
    document itself writes it name-first ("Sayın İdris ŞAHİN\\nAnkara
    Milletvekili") -- the exact substring check rejected this correct
    value outright. Token overlap (both "significant" tokens still present,
    just reordered) rescues it instead."""
    doc = (
        "Sayı : Z-1\nTarih : 02.04.2026\nKonu : Soru Önergesi\n\n"
        "Sayın İdris ŞAHİN\nAnkara Milletvekili\n\n"
        "İlgi : bir şey.\n\nMetin.\nRica ederim.\n\n"
        "Bekir BOZDAĞ\nTürkiye Büyük Millet Meclisi\nBaşkanvekili"
    )
    merged = merge_parsed_over_model(
        {"muhatap": "Ankara Milletvekili İdris ŞAHİN"}, {}, document_text=doc
    )
    assert merged["muhatap"] == "Ankara Milletvekili İdris ŞAHİN"


def test_token_overlap_does_not_rescue_an_unrelated_fabrication():
    """The tolerant fallback must still reject a value whose tokens simply
    don't appear in a document that names no addressee at all."""
    doc = (
        "T.C.\nÖRNEK BAKANLIĞI\n\nKonu : Bir şey\n\n"
        "Bu belgede hiç muhatap veya makam adı geçmiyor sadece metin var.\n\n"
        "Ahmet YILMAZ"
    )
    merged = merge_parsed_over_model({"muhatap": "FANTEZİ VALİLİĞİNE"}, {}, document_text=doc)
    assert merged["muhatap"] is None


def test_konu_paraphrase_is_not_rescued_by_token_overlap():
    """Real live case, measured against qwen3.5:9b on CY-010 -- a document
    with no "Konu:" line at all. The model built a `konu` value by lightly
    rewording body vocabulary ("...istemlerine ilişkin ilgi önergenizde
    yer alan sorularınız..." into "...istemlerine ilişkin soruların
    cevabı"), which scores 0.857 token overlap despite being a synthesised
    summary, not an extracted value -- `konu` must therefore stay off the
    token-overlap path entirely (`_TOKEN_OVERLAP_ELIGIBLE_FIELD` excludes
    it), unlike `muhatap`/`gonderen_kurum` where reordering, not
    paraphrase, is the realistic failure mode."""
    doc = (
        "TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞI\nKanunlar ve Kararlar Başkanlığı\n\n"
        "Sayı : Z-1\nTarih : 20.04.2026\n\n"
        "Sayın Ceylan AKÇA CUPOLO\nDiyarbakır Milletvekili\n\n"
        "TBMM Başkanlığına gelen yasama dokunulmazlığının kaldırılması istemlerine "
        "ilişkin ilgi önergenizde yer alan sorularınız ekte cevaplandırılmıştır.\n"
        "Bilgilerinizi rica ederim.\n\nBekir BOZDAĞ\nBaşkanvekili"
    )
    merged = merge_parsed_over_model(
        {"konu": "Yasama dokunulmazlığının kaldırılması istemlerine ilişkin soruların cevabı"},
        {},
        document_text=doc,
    )
    assert merged["konu"] is None


def test_body_text_date_is_not_rescued_into_tarih():
    """The documented failure mode this rule exists to prevent: a leave
    request's start date, which the model may read out of the body, must
    not be accepted as the header's own `tarih` just because it appears
    somewhere in the document -- it has to appear in the header region,
    before the addressee/closing formula."""
    doc = (
        "T.C.\nÖRNEK BAKANLIĞI\n\nKonu : İzin\n\nSAYIN VALİLİĞİNE\n\n"
        "01.06.2026 tarihinden itibaren izinli olmak istiyorum.\n"
        "Bilgilerinize arz ederim.\n\nAhmet YILMAZ"
    )
    merged = merge_parsed_over_model({"tarih": "01.06.2026"}, {}, document_text=doc)
    assert merged["tarih"] is None


def test_header_region_date_is_rescued_into_tarih():
    doc = (
        "T.C.\nÖRNEK BAKANLIĞI\n\n12.05.2026 tarihli yazı\n\nSAYIN VALİLİĞİNE\n\n"
        "Metin.\nArz ederim.\n\nAhmet YILMAZ"
    )
    merged = merge_parsed_over_model({"tarih": "12.05.2026"}, {}, document_text=doc)
    assert merged["tarih"] == "12.05.2026"


def test_unsigned_petition_signature_is_not_resurrected_even_with_document_text():
    """The critical regression this evidence-based rescue must not cause:
    `imza_sahibi` is deliberately excluded from `_EVIDENCE_RESCUABLE_FIELD`
    (see that set's own docstring), so even though "Ali Vural" is literally
    present in `UNSIGNED_PETITION`'s own text, it must stay discarded --
    exactly as it does without `document_text` at all."""
    parsed = parse_labelled_fields(UNSIGNED_PETITION)
    merged = merge_parsed_over_model(
        {"imza_sahibi": "Ali Vural"}, parsed, document_text=UNSIGNED_PETITION
    )
    assert merged["imza_sahibi"] is None


# ==========================================
# OCR-artefact tolerance (regression tests for real scanned-corpus failures)
#
# Found calibrating the header-escalation gate against all 45 scanned CY-*.pdf
# in datasets/resmi_yazisma/00_gelen_kaynaklar/cevap_yazisi/: real Tesseract
# output consistently mangles specific characters around these labels in ways
# a synthetic sample never exercised. Each pattern below is the exact shape
# observed, reduced to a minimal case.
# ==========================================
def test_tarih_is_read_unlabelled_from_the_end_of_the_sayi_line():
    """Standard RYUEHY layout puts the date at the right of the Sayı line with
    no 'Tarih' label at all -- distinct from test_sayi_and_tarih_may_share_one_line,
    which covers the labelled case. Real example (CY-012):
    'Sayı : Z-88839574-610-2026/7061-6048344 16 Nisan 2026'."""
    parsed = parse_labelled_fields("Sayı : Z-88839574-610-2026/7061-6048344 16 Nisan 2026")
    assert parsed["tarih"] == "16 Nisan 2026"


def test_unlabelled_tarih_also_reads_numeric_dates():
    parsed = parse_labelled_fields("Sayı : E-12345-610-2026 20.04.2026")
    assert parsed["tarih"] == "20.04.2026"


def test_labelled_tarih_still_takes_precedence_over_the_unlabelled_pattern():
    """The labelled form (m.12) must keep winning when both are present."""
    parsed = parse_labelled_fields("Sayı : E-1-2-3   Tarih : 12.03.2026")
    assert parsed["tarih"] == "12.03.2026"


def test_tarih_is_read_from_its_own_line_right_after_sayi():
    """Some vision-model transcriptions break the date onto its own line
    instead of keeping it glued to the Sayı line -- distinct from
    test_tarih_is_read_unlabelled_from_the_end_of_the_sayi_line, which covers
    the same-line case. Real example (CY-010, glm-ocr:latest header repair):
    'Sayı : Z-43452547-120.07.03-1841896\\n20.04.2026\\nKonu : Soru Önergesi'."""
    text = "Sayı : Z-43452547-120.07.03-1841896\n20.04.2026\nKonu : Soru Önergesi"
    parsed = parse_labelled_fields(text)
    assert parsed["tarih"] == "20.04.2026"


def test_labelled_tarih_still_takes_precedence_over_the_next_line_pattern():
    """The labelled form (m.12) must keep winning over the next-line fallback too."""
    text = "Sayı : E-1-2-3\nTarih : 12.03.2026\nKonu : Deneme"
    parsed = parse_labelled_fields(text)
    assert parsed["tarih"] == "12.03.2026"


def test_same_line_tarih_still_takes_precedence_over_the_next_line_pattern():
    """If the date is already found glued to the Sayı line, an unrelated date
    appearing on the very next line (e.g. a second reference number's own
    date) must not override it."""
    text = "Sayı : Z-1 16 Nisan 2026\n20.04.2026\nKonu : Deneme"
    parsed = parse_labelled_fields(text)
    assert parsed["tarih"] == "16 Nisan 2026"


def test_next_line_tarih_pattern_does_not_reach_past_a_blank_body_paragraph():
    """A date appearing later in the body, separated from Sayı by ordinary
    content, must not be mistaken for the header date."""
    text = (
        "Sayı : Z-1\n"
        "Konu : Deneme\n\n"
        "Bu yazı 20.04.2026 tarihinde hazırlanmıştır.\n"
    )
    parsed = parse_labelled_fields(text)
    assert "tarih" not in parsed


def test_gonderen_kurum_survives_a_stray_character_glued_onto_the_tc_line():
    """Real OCR (CY-023/027/028/030): a decorative border/emblem glyph is
    misread as a stray leading character on the same line as 'T.C.'
    ('* T.C.', ', T.C.'), which the exact-match anchor used to reject outright."""
    text = "* T.C.\nÖRNEK BAKANLIĞI\nPersonel Genel Müdürlüğü\n\nKonu : Deneme"
    parsed = parse_labelled_fields(text)
    assert parsed["gonderen_kurum"] == "ÖRNEK BAKANLIĞI Personel Genel Müdürlüğü"


def test_muhatap_survives_an_incidental_miscased_letter_within_the_line():
    """Real scanned-corpus OCR sometimes renders one letter of an otherwise
    upper-case addressee line as lower-case ("ÖRNEK VALİLİğİNE"). The original
    pattern required every character before the suffix to be non-lower-case,
    so a single miscased letter anywhere lost the whole line; the fix keeps
    that requirement off the run before the suffix, while keeping the suffix
    itself upper-case-only -- see the comment on `_ADDRESSEE_LINE` for why
    that second half matters."""
    parsed = parse_labelled_fields(OFFICIAL_LETTER.replace("ÖRNEK VALİLİĞİNE", "ÖRNEK VALİLİğİNE"))
    assert parsed["muhatap"] == "ÖRNEK VALİLİğİNE"


def test_addressee_pattern_does_not_match_an_ordinary_body_sentence():
    """Regression guard: a fully case-insensitive fix attempt matched ordinary
    prose ending in a dative-suffixed word (extremely common in Turkish),
    which corrupted `muhatap` with body text instead of the real addressee --
    and, because `_parse_sender_institution` also stops at an
    `_ADDRESSEE_LINE` match, corrupted `gonderen_kurum` too. Both must still
    resolve correctly here."""
    text = (
        "T.C.\nÖRNEK BAKANLIĞI\n\nKonu : Deneme\n\n"
        "ÖRNEK VALİLİĞİNE\n\n"
        "Bakanlığımız görev ve yetki alanına giren hususlar itibarıyla önergenize "
        "ilişkin cevaplarımıza aşağıda yer verilmiştir ve konuya ilişkin bilgi sunulmuştur.\n\n"
        "Metin arz ederim.\n\nAhmet Yılmaz\nGenel Müdür"
    )
    parsed = parse_labelled_fields(text)
    assert parsed["muhatap"] == "ÖRNEK VALİLİĞİNE"
    assert parsed["gonderen_kurum"] == "ÖRNEK BAKANLIĞI"


def test_addressee_pattern_does_not_match_a_capitalised_name():
    """Regression guard: the same case-insensitive fix attempt also matched
    an ordinary Title Case person's name ('Zeynep Kaya', from a real sample
    document's signature block) as if it were an addressee, because 'Kaya'
    happens to end in 'ya' -- indistinguishable, by letters alone, from a
    genuine dative-case institution name in Title Case. Requiring the suffix
    itself to stay upper-case rules this out."""
    text = "T.C.\nÖRNEK BAKANLIĞI\n\nKonu : Deneme\n\nÖRNEK VALİLİĞİNE\n\nMetin.\n\nZeynep Kaya"
    parsed = parse_labelled_fields(text)
    assert parsed["muhatap"] == "ÖRNEK VALİLİĞİNE"


def test_muhatap_survives_a_handwritten_annotation_on_the_same_line():
    """Real OCR on CY-012 (from the real scanned corpus, not synthetic): a
    handwritten reference number ('7/42413') sits to the right of the
    addressee line on the page, and a vision model reading it accurately
    ('7/4/2413') places it on the same text line as the addressee --
    'TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA 7/4/2413'. The original
    pattern anchored on '$' right after the suffix, so this correctly-read
    annotation broke the match entirely and muhatap came back None -- the
    better the OCR read the handwriting, the worse this field scored. Fix:
    tolerate exactly one short *digits-and-slashes* trailing token after the
    suffix (not any short token -- see the two false-positive regression
    tests just below for why that first, broader attempt was unsafe)."""
    text = (
        "T.C.\nÖRNEK BAKANLIĞI\n\nKonu : Deneme\n\n"
        "TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA 7/4/2413\n\n"
        "Metin arz ederim.\n\nAhmet Yılmaz\nGenel Müdür"
    )
    parsed = parse_labelled_fields(text)
    assert parsed["muhatap"] == "TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA 7/4/2413"


def test_addressee_pattern_does_not_match_an_institution_name_ending_in_the_suffix():
    """Regression guard, found by an A/B run against the real 45-document
    corpus holding OCR output fixed and comparing old vs new parser output
    (not asserted from first principles -- the earlier `\\S{1,12}` version of
    this tolerance passed every unit test and still broke live on real data).
    'HAZİNE VE MALİYE BAKANLIĞI' is an institution's own letterhead line, not
    an addressee -- but 'MALİYE' ends in 'YE' and 'BAKANLIĞI' is one short
    token, so the broad version matched it anyway. Because
    `_parse_addressee` returns the *first* matching line, that false match
    both stole the result from the real addressee lower in the document and,
    via `_parse_sender_institution`'s shared break condition, zeroed out
    every `gonderen_kurum` recovery on the 6 real documents sharing this
    letterhead (CY-023/028/029/030/038/042). Restricting the trailing
    annotation to `[0-9/]` closes this without losing the CY-012 case above."""
    text = (
        "T.C.\nHAZİNE VE MALİYE BAKANLIĞI\nStrateji Geliştirme Başkanlığı\n\n"
        "Konu : Deneme\n\n"
        "TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA 7/42045\n\n"
        "Metin arz ederim.\n\nAhmet Yılmaz\nGenel Müdür"
    )
    parsed = parse_labelled_fields(text)
    assert parsed["muhatap"] == "TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA 7/42045"
    assert parsed["gonderen_kurum"] == "HAZİNE VE MALİYE BAKANLIĞI Strateji Geliştirme Başkanlığı"


def test_addressee_pattern_does_not_match_ocr_garbage_ending_in_the_suffix():
    """Second real false positive from the same A/B run: OCR footer noise on
    CY-004 ('İnternet Adresi: Www.tccb. gov.tr MİDYE İN') coincidentally ends
    in 'MİDYE' (which contains 'YE') followed by the short garbage token
    'İN', matching the broad `\\S{1,12}` version and replacing the real
    (unrecoverable on that document, but that is a separate, honest gap --
    see CY-010 in the real-corpus ground truth) muhatap with noise."""
    text = (
        "T.C.\nÖRNEK BAKANLIĞI\n\nKonu : Deneme\n\n"
        "Metin arz ederim.\n\n"
        "İnternet Adresi: Www.tccb. gov.tr MİDYE İN\n"
    )
    parsed = parse_labelled_fields(text)
    assert "muhatap" not in parsed


def test_sayi_survives_a_stray_glyph_before_its_colon():
    """Real OCR (CY-001/005/007/008/013/019...): a form checkbox glyph is
    consistently misread as '(o' between the label and its colon
    ('Sayı (o :E-48360949-610-375523'), which the exact `label:` anchor used
    to reject outright -- this single bug alone accounted for the majority of
    missing `sayi` values across the 45-document scanned corpus."""
    parsed = parse_labelled_fields("Sayı (o :E-48360949-610-375523\nKonu : Deneme")
    assert parsed["sayi"] == "E-48360949-610-375523"


def test_stray_glyph_tolerance_does_not_swallow_a_real_short_label_value():
    """The tolerance is capped at 3 characters specifically so it cannot eat
    into a genuine value when the label:value format is completely normal."""
    parsed = parse_labelled_fields("Sayı : E-1\nKonu : X")
    assert parsed["sayi"] == "E-1"
    assert parsed["konu"] == "X"


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


# --- count_header_fields ---------------------------------------------------
#
# Backs the extraction-acceptance gate's field-aware criterion (see
# FallbackDocumentExtractor._has_enough_header_fields): whether an extraction
# is good enough is decided by how many of these five fields survive, not by
# prose readability, which is structurally blind to header damage (a garbled
# `sayi` still reads as fine Turkish prose overall).


def test_header_field_is_exactly_the_five_ryuehy_header_fields():
    assert HEADER_FIELD == ("sayi", "tarih", "konu", "muhatap", "gonderen_kurum")


def test_count_header_fields_counts_all_five_on_a_clean_letter():
    assert count_header_fields(OFFICIAL_LETTER) == 5


def test_count_header_fields_is_zero_on_free_text_with_no_labels():
    assert count_header_fields("Bu bir deneme metnidir, hiçbir etiket içermez.") == 0


def test_count_header_fields_only_counts_the_five_header_keys():
    """A document that parses `ilgi`/`ekler`/`imza_sahibi` etc. but none of the
    five header fields must still count as zero -- those aren't header fields."""
    text = "İlgi : 01.03.2026 tarihli yazı.\nEkler : 1- Nüfus cüzdanı örneği"
    assert parse_labelled_fields(text).get("ilgi")  # sanity: something did parse
    assert count_header_fields(text) == 0
