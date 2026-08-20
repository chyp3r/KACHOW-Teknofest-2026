"""Unit tests for the pure entity-resolution pipeline.

`resolve_entities` is a pure function: raw surface-form strings in, a mapping
from each raw string to its `ResolvedEntity` out. No I/O.

Every fixture string below is copied verbatim from the real 14-document
corpus (`backend/storage_data/uploads/*_analysis.json`, `fields.muhatap` /
`fields.entities` / `fields.gonderen_kurum`) -- not fabricated. See the
session plan's measurement table for the full picture; this file pins the
specific cases that motivated each pipeline step.
"""

import random

from app.domains.documents.entity_resolution import resolve_entities

# The four real surface forms of one institution, verbatim from the corpus.
_MUHATAP_MARKDOWN = "##### TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA (Kanunlar ve Kararlar Başkanlığı)"
_MUHATAP_WITH_LEAKED_NUMBER = "TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA 741393 (Kanunlar ve Kararlar Başkanlığı)"
_MUHATAP_PLAIN = "TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA"
_MUHATAP_OCR_DAMAGED = "TÜRKIYE BÜYÜK MILLET MECLISI BASKANLIÇINA"  # Ğ misread as Ç


def test_markdown_parenthetical_and_leaked_number_all_canonicalize_identically():
    resolved = resolve_entities([_MUHATAP_MARKDOWN, _MUHATAP_WITH_LEAKED_NUMBER, _MUHATAP_PLAIN])
    keys = {resolved[raw].key for raw in (_MUHATAP_MARKDOWN, _MUHATAP_WITH_LEAKED_NUMBER, _MUHATAP_PLAIN)}
    assert len(keys) == 1


def test_urgency_and_dative_suffixes_are_stripped_so_sender_and_addressee_forms_merge():
    # Real gonderen_kurum vs. muhatap forms of the same office pair -- one
    # carries a leaked urgency marker, the other a dative case ending.
    sender = "CUMHURBAŞKANI YARDIMCISI GÜNLÜDÜR"
    sender_plain = "CUMHURBAŞKANI YARDIMCISI"
    resolved = resolve_entities([sender, sender_plain])
    assert resolved[sender].key == resolved[sender_plain].key


def test_dative_ending_stripped_from_the_final_token_only():
    resolved = resolve_entities([_MUHATAP_PLAIN])
    # "...BAŞKANLIĞINA" -> "...BAŞKANLIĞI": only the dative "-na" comes off,
    # the possessive "-ı" that precedes it must survive.
    assert resolved[_MUHATAP_PLAIN].key.endswith("baskanligi")
    assert not resolved[_MUHATAP_PLAIN].key.endswith("baskanlig")


def test_clustering_is_independent_of_input_order():
    raw_forms = [_MUHATAP_MARKDOWN, _MUHATAP_WITH_LEAKED_NUMBER, _MUHATAP_PLAIN, _MUHATAP_OCR_DAMAGED]
    baseline = resolve_entities(raw_forms)
    baseline_keys = {raw: baseline[raw].key for raw in raw_forms}

    shuffled = list(raw_forms)
    rng = random.Random(1234)
    for _ in range(5):
        rng.shuffle(shuffled)
        result = resolve_entities(shuffled)
        assert {raw: result[raw].key for raw in raw_forms} == baseline_keys


def test_ocr_damaged_form_fuzzy_merges_with_the_clean_forms():
    resolved = resolve_entities([_MUHATAP_PLAIN, _MUHATAP_OCR_DAMAGED])
    assert resolved[_MUHATAP_PLAIN].key == resolved[_MUHATAP_OCR_DAMAGED].key


def test_a_genuinely_different_institution_is_not_fuzzy_merged():
    resolved = resolve_entities([_MUHATAP_PLAIN, "SANAYİ VE TEKNOLOJİ BAKANLIĞI"])
    assert resolved[_MUHATAP_PLAIN].key != resolved["SANAYİ VE TEKNOLOJİ BAKANLIĞI"].key


def test_two_ministries_sharing_a_common_suffix_are_not_merged():
    # "MİLLİ SAVUNMA BAKANLIĞI" vs "MİLLİ EĞİTİM BAKANLIĞI" -- measured
    # SequenceMatcher ratio 0.756, closer to the 0.88 threshold than any
    # other pair in this corpus, so this is the adversarial case that
    # actually stresses the threshold rather than one that trivially passes.
    resolved = resolve_entities(["MİLLİ SAVUNMA BAKANLIĞI", "MİLLİ EĞİTİM BAKANLIĞI"])
    assert resolved["MİLLİ SAVUNMA BAKANLIĞI"].key != resolved["MİLLİ EĞİTİM BAKANLIĞI"].key


def test_display_label_strips_leading_markdown_junk_even_when_that_form_is_most_frequent():
    # Measured on the real, live 14-document corpus (not a synthetic case):
    # the markdown-prefixed form is the *most frequent* raw surface form (5
    # of 11 occurrences, vs. 4 for the clean form) -- naive "most frequent
    # wins" would put "##### TÜRKİYE ... (Kanunlar ve Kararlar Başkanlığı)"
    # on a graph node's label, in front of a jury. The trailing parenthetical
    # is real information (a sub-office within TBMM) and must survive; only
    # the leading markdown noise is stripped.
    raw_forms = [_MUHATAP_MARKDOWN] * 5 + [_MUHATAP_PLAIN] * 4
    resolved = resolve_entities(raw_forms)
    label = resolved[_MUHATAP_MARKDOWN].label
    assert not label.startswith("#")
    assert label.startswith("TÜRKİYE")
    assert "(Kanunlar ve Kararlar Başkanlığı)" in label
    # The raw, unstripped form must still be disclosed among surface_forms
    # -- only the display label is cleaned.
    assert _MUHATAP_MARKDOWN in resolved[_MUHATAP_MARKDOWN].surface_forms


def test_display_label_is_the_most_frequent_original_surface_form_not_the_folded_key():
    # Plain form appears 3x (matches the real corpus's 4th vs other counts
    # closely enough to exercise majority selection), markdown form once.
    resolved = resolve_entities([_MUHATAP_PLAIN, _MUHATAP_PLAIN, _MUHATAP_PLAIN, _MUHATAP_MARKDOWN])
    assert resolved[_MUHATAP_PLAIN].label == _MUHATAP_PLAIN
    assert resolved[_MUHATAP_MARKDOWN].label == _MUHATAP_PLAIN  # same cluster, same label


def test_every_merged_surface_form_is_retained_for_disclosure():
    raw_forms = [_MUHATAP_MARKDOWN, _MUHATAP_WITH_LEAKED_NUMBER, _MUHATAP_PLAIN, _MUHATAP_OCR_DAMAGED]
    resolved = resolve_entities(raw_forms)
    forms = set(resolved[_MUHATAP_PLAIN].surface_forms)
    assert forms == set(raw_forms)


def test_institution_entity_is_classified_as_kurum():
    resolved = resolve_entities(["Türkiye Büyük Millet Meclisi Başkanlığı"])
    assert resolved["Türkiye Büyük Millet Meclisi Başkanlığı"].kind == "kurum"


def test_person_entity_is_classified_as_kisi():
    resolved = resolve_entities(["İdris ŞAHİN"])
    assert resolved["İdris ŞAHİN"].kind == "kisi"


def test_short_uppercase_abbreviation_is_classified_as_kurum_not_kisi():
    # NATO/TBMM/BTK are single all-caps tokens -- never a plausible person
    # name shape, and misclassifying them as "kisi" would be worse than an
    # honest "diger".
    resolved = resolve_entities(["NATO", "TBMM", "BTK"])
    assert resolved["NATO"].kind == "kurum"
    assert resolved["TBMM"].kind == "kurum"
    assert resolved["BTK"].kind == "kurum"


def test_empty_and_none_entries_are_skipped_without_crashing():
    resolved = resolve_entities(["", None, "  ", "İdris ŞAHİN"])
    assert "İdris ŞAHİN" in resolved
    assert len(resolved) == 1


def test_empty_input_returns_empty_mapping():
    assert resolve_entities([]) == {}


def test_full_real_muhatap_column_collapses_to_two_clusters():
    # Every real muhatap value from the 14-document corpus, verbatim,
    # including the two non-TBMM outliers ("DAĞITIM YERLERİNE",
    # "ÖRNEK KAYMAKAMLIĞINA") which must NOT merge into the TBMM cluster.
    raw_forms = (
        [_MUHATAP_WITH_LEAKED_NUMBER]
        + [_MUHATAP_MARKDOWN] * 5
        + [_MUHATAP_PLAIN] * 4
        + [_MUHATAP_OCR_DAMAGED]
        + ["DAĞITIM YERLERİNE"] * 2
        + ["ÖRNEK KAYMAKAMLIĞINA"]
    )
    resolved = resolve_entities(raw_forms)
    tbmm_keys = {
        resolved[raw].key
        for raw in (_MUHATAP_WITH_LEAKED_NUMBER, _MUHATAP_MARKDOWN, _MUHATAP_PLAIN, _MUHATAP_OCR_DAMAGED)
    }
    assert len(tbmm_keys) == 1
    tbmm_key = next(iter(tbmm_keys))
    assert resolved["DAĞITIM YERLERİNE"].key != tbmm_key
    assert resolved["ÖRNEK KAYMAKAMLIĞINA"].key != tbmm_key
    tbmm_docs = sum(
        1
        for raw in raw_forms
        if resolved[raw].key == tbmm_key
    )
    assert tbmm_docs == 11
