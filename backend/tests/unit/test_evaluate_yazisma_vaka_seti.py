"""Deterministik gelen evrak-karar-cevap kalite kapısı testleri."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import evaluate_yazisma_vaka_seti as evaluator  # noqa: E402


def _valid_case(case_id="GKC-TAM_KABUL-008"):
    return {
        "case_id": case_id,
        "incoming_document": "T.C.\nİZMİR VALİLİĞİ\nBaşvuru konusu eğitim desteğidir.",
        "incoming_type": "dilekce",
        "requested_action": "Eğitim desteği talebi",
        "decision": "tam_kabul",
        "decision_reason": "Talep uygun bulunmuştur.",
        "outgoing_correspondence_type": "cevap_yazisi",
        "required_facts": [
            {
                "alan": "başvuru konusu",
                "deger": "eğitim desteği",
                "kaynak_satir": "Başvuru konusu eğitim desteğidir.",
            }
        ],
        "missing_information": [],
        "expected_questions": [],
        "gold_draft": "T.C.\nİZMİR VALİLİĞİ\nEğitim desteği talebiniz uygun bulunmuştur.",
        "must_include": ["uygun bulunmuştur"],
        "must_not_invent": ["olmayan sözleşme numarası"],
        "legal_basis": [],
        "evidence": [{"tur": "uslup_referansi"}],
        "source_origin": "sentetik_kurgu",
        "provenance": {
            "kurum_tahmini": "İZMİR VALİLİĞİ",
            "uslup_referanslari": [
                {
                    "kaynak_kart_id": "CY-001",
                    "kaynak_yolu": "datasets/resmi_yazisma/CY-001.md",
                    "kaynak_sha256": "a" * 64,
                    "source_group": "b" * 16,
                }
            ],
        },
        "anonymization": {"denetim_durumu": "uygun"},
        "review_status": "taslak",
        "source_group": "tpl-1234567890abcdef",
        "dataset_split": "n/a",
    }


def test_valid_case_passes_the_gate():
    report = evaluator.evaluate_cases([_valid_case()])

    assert report["gate_status"] == "passed"
    assert report["error_count"] == 0


def test_duplicate_case_id_fails_the_gate():
    case = _valid_case()
    report = evaluator.evaluate_cases([case, dict(case)])

    assert report["gate_status"] == "failed"
    assert report["finding_distribution"]["tekrar_case_id"] == 1


def test_itiraz_quota_requires_itiraz_incoming_type():
    case = _valid_case("GKC-TAM_KABUL-001")
    report = evaluator.evaluate_cases([case])

    assert report["finding_distribution"]["itiraz_kotasi_uyusmazligi"] == 1


def test_unverified_legal_basis_fails_the_gate():
    case = _valid_case()
    case["legal_basis"] = [
        {
            "type": "kanun",
            "number": "4982",
            "title": "BİLGİ EDİNME HAKKI KANUNU",
            "article": "",
            "verification_source": "model",
            "verification_status": "iddia",
        }
    ]

    report = evaluator.evaluate_cases([case])

    assert report["finding_distribution"]["mevzuat_dogrulanmamis"] == 1
    assert report["finding_distribution"]["mevzuat_kaynagi_gecersiz"] == 1


def test_missing_required_fact_in_draft_fails_the_gate():
    case = _valid_case()
    case["gold_draft"] = "Talebiniz uygun bulunmuştur."

    report = evaluator.evaluate_cases([case])

    assert report["finding_distribution"]["olgu_taslagina_tasinmadi"] == 1
