"""Tests for the official GİB and TÜRKPATENT corpus collectors."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import collect_gib_official_corpus as gib  # noqa: E402
import collect_turkpatent_missing_document_examples as turkpatent  # noqa: E402


def test_gib_compaction_preserves_beginning_and_conclusion_of_long_text():
    text = "\n".join(
        ["T.C. GELİR İDARESİ BAŞKANLIĞI", "İlgide kayıtlı talebiniz incelenmiştir."]
        + [f"Mevzuat açıklaması {index}." * 10 for index in range(80)]
        + ["Sonuç olarak talebiniz uygun bulunmuştur.", "Bilgi edinilmesini rica ederim."]
    )

    compacted = gib._compact(text)

    assert len(compacted) <= gib.MAX_CARD_CHARS
    assert compacted.startswith("T.C. GELİR İDARESİ BAŞKANLIĞI")
    assert "[MEVZUAT ALINTILARI KISALTILMIŞTIR]" in compacted
    assert compacted.endswith("Bilgi edinilmesini rica ederim.")


def test_gib_anonymisation_uses_semantic_placeholders():
    text = (
        "Sayı: E-62030549-125[26-74]-123456\n"
        "İlgi: …. tarihli başvurunuz.\n"
        "Şirketinizin …. merkezli şirketle yaptığı işlem.\n"
        "Telefon: 0532 123 45 67, e-posta: kisi@example.org"
    )

    anonymised, count = gib._anonymise(text)

    assert count >= 5
    assert "62030549" not in anonymised
    assert "0532 123 45 67" not in anonymised
    assert "kisi@example.org" not in anonymised
    assert "[EVRAK SAYISI]" in anonymised
    assert "[BAŞVURU BİLGİSİ]" in anonymised
    assert "[KURUM ADI]" in anonymised
    assert "[TELEFON]" in anonymised
    assert "[E-POSTA]" in anonymised


def test_placeholder_cannot_be_mistaken_for_a_source_institution():
    text = "T.C.\nGELİR İDARESİ BAŞKANLIĞI\n[BAŞVURUYA ÖZGÜ BİLGİ] Defterdarlığı"

    assert gib._institution(text) == "Gelir İdaresi Başkanlığı"


def test_response_intent_distinguishes_positive_negative_and_mixed_results():
    assert gib._response_intent("Yararlanmanız mümkün bulunmaktadır.")[1] == "olumlu_cevap"
    assert gib._response_intent("Yararlanmanız mümkün bulunmamaktadır.")[1] == "ret"
    assert (
        gib._response_intent(
            "Birinci işlem mümkün bulunmaktadır; ikinci işlem mümkün bulunmamaktadır."
        )[1]
        == "ret_kismen_kabul"
    )


def test_turkpatent_anonymisation_masks_record_application_and_mark_name():
    text = (
        'Evrak No: 220329436 Başvuru No: 2019/27231\n'
        'İlgi: 2019-GE-117737 sayılı dilekçeniz.\n'
        '2019/27231 numaralı "örnek marka" ibareli başvurunuz incelenmiştir.'
    )

    anonymised, count = turkpatent._anonymise(text)

    assert count == 5
    assert "220329436" not in anonymised
    assert "2019/27231" not in anonymised
    assert "2019-GE-117737" not in anonymised
    assert "örnek marka" not in anonymised
    assert "[EVRAK SAYISI]" in anonymised
    assert "[BAŞVURU NUMARASI]" in anonymised
    assert "[İLGİ EVRAK SAYISI]" in anonymised
    assert "[MARKA ADI]" in anonymised


def test_generated_analysis_meets_real_document_floor_for_every_type():
    analysis_path = os.path.join(gib.CORPUS_ROOT, "rag-veri-analizi.json")
    with open(analysis_path, encoding="utf-8") as handle:
        analysis = json.load(handle)

    assert set(analysis["real_count_by_type"]) == {
        "cover_letter",
        "information_notice",
        "other_official",
        "response_letter",
    }
    assert all(count >= 100 for count in analysis["real_count_by_type"].values())
    assert analysis["response_real_count_by_intent"]["eksik_belge_yetkisizlik"] >= 10
    assert analysis["pii_flagged_count"] == 0
    assert analysis["duplicate_template_families"] == 0
