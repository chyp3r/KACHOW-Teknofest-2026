"""Unit tests for scripts/generate_yazisma_vaka_pilotu.py's pure logic.

No LLM/Evren/mevzuat-MCP calls here -- those need a live API key and
network, and are exercised manually per VAKA_URETIM_PLAYBOOK.md. This file
only covers the deterministic schema guard and text-safety helpers.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import generate_yazisma_vaka_pilotu as pilot  # noqa: E402


def test_allowed_decisions_matches_the_plan_document_enum():
    """The 8-value decision enum from GELEN_EVRAK_KARAR_CEVAP_VERI_PLANI.md.
    ``itiraz`` must never be a member: it is an incoming_type, not a
    decision (see the schema-fix note in TARGET_DECISIONS's docstring)."""
    assert pilot.ALLOWED_DECISIONS == {
        "tam_kabul",
        "ret",
        "kismi_kabul",
        "eksik_belge",
        "yetkisizlik",
        "yalnizca_bilgilendirme",
        "belirsiz_basvuru",
        "coklu_talep",
    }
    assert "itiraz" not in pilot.ALLOWED_DECISIONS


def test_target_decisions_covers_exactly_the_allowed_decisions():
    """Aşama 2/3: the 240-case quota must cover all 8 decision types
    exactly once each -- no missing type, no invalid key (this is exactly
    how ``itiraz`` ended up as a decision value in the first pilot run).
    The module already asserts this at import time; this test documents
    and pins that behaviour."""
    assert pilot.TARGET_DECISIONS.keys() == pilot.ALLOWED_DECISIONS


def test_target_decisions_quota_sums_to_240():
    assert sum(spec["adet"] for spec in pilot.TARGET_DECISIONS.values()) == 240
    assert pilot.TOTAL_TARGET_CASES == 240


def test_itiraz_quota_meets_minimum_and_overall_share_target():
    """Every decision type must carry at least ITIRAZ_MIN_PER_DECISION
    itiraz cases, and the total itiraz share across all 240 must land in
    the planned 15-20% band."""
    per_decision = {
        decision: pilot._itiraz_count_for(spec["adet"])
        for decision, spec in pilot.TARGET_DECISIONS.items()
    }
    for decision, count in per_decision.items():
        assert count >= pilot.ITIRAZ_MIN_PER_DECISION, decision

    total_itiraz = sum(per_decision.values())
    share = total_itiraz / pilot.TOTAL_TARGET_CASES
    assert pilot.ITIRAZ_MIN_SHARE <= share <= pilot.ITIRAZ_MAX_SHARE, share


def test_each_decision_has_enough_real_few_shot_examples():
    """A quota whose few_shot_glob/niyet_filter can't find at least
    FEW_SHOT_PER_TYPE real candidate cards would silently degrade to
    'atlandı' for every case of that type during the real run -- this
    check catches that before any Evren call is spent."""
    for decision, spec in pilot.TARGET_DECISIONS.items():
        examples = pilot._load_few_shots(
            spec["few_shot_glob"], pilot.FEW_SHOT_PER_TYPE, niyet_filter=spec.get("niyet_filter")
        )
        assert len(examples) >= pilot.FEW_SHOT_PER_TYPE, (
            decision,
            spec["few_shot_glob"],
            spec.get("niyet_filter"),
        )


def test_extract_institution_reads_a_letterhead_line():
    # A gold_draft's own letterhead, not an incoming petition's addressee
    # line -- _extract_institution reads who is SPEAKING, matched against
    # prepare_resmi_yazisma_markdown._INSTITUTION_LINE's known suffixes
    # (BAKANLIĞI/VALİLİĞİ/KAYMAKAMLIĞI/...).
    text = "T.C.\nİZMİR VALİLİĞİ\nİl Sağlık Müdürlüğü\n\nSayı: E-2026/1"
    assert pilot._extract_institution(text) == "İZMİR VALİLİĞİ"


def test_extract_institution_returns_none_without_a_letterhead():
    assert pilot._extract_institution("Sayın Yetkili, başvurumu inceleyiniz.") is None


def test_load_existing_case_ids_reads_case_ids_for_resume(tmp_path):
    path = tmp_path / "vakalar.jsonl"
    path.write_text(
        '{"case_id": "GKC-RET-001", "x": 1}\n{"case_id": "GKC-RET-002", "x": 2}\n',
        encoding="utf-8",
    )
    assert pilot._load_existing_case_ids(path) == {"GKC-RET-001", "GKC-RET-002"}


def test_load_existing_case_ids_is_empty_for_a_missing_file(tmp_path):
    assert pilot._load_existing_case_ids(tmp_path / "yok.jsonl") == set()


def test_append_jsonl_is_additive_and_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "vakalar.jsonl"

    pilot._append_jsonl(path, {"case_id": "GKC-RET-001"})
    pilot._append_jsonl(path, {"case_id": "GKC-RET-002"})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [pilot.json.loads(l)["case_id"] for l in lines] == [
        "GKC-RET-001",
        "GKC-RET-002",
    ]


def test_incoming_type_itiraz_constant_is_not_a_decision():
    assert pilot.INCOMING_TYPE_ITIRAZ not in pilot.ALLOWED_DECISIONS
    assert pilot.INCOMING_TYPE_ITIRAZ == "itiraz"


def test_case_id_is_deterministic_and_encodes_the_decision():
    assert pilot._case_id("tam_kabul", 3) == "GKC-TAM_KABUL-003"
    assert pilot._case_id("tam_kabul", 3) == pilot._case_id("tam_kabul", 3)


@pytest.mark.parametrize("decision", sorted(pilot.ALLOWED_DECISIONS))
def test_case_id_accepts_every_allowed_decision(decision):
    case_id = pilot._case_id(decision, 1)
    assert case_id.startswith("GKC-")
    assert decision.upper() in case_id


def test_scrub_reported_names_masks_every_residual_occurrence():
    text = "Başvuran Mehmet Demir, komşusu Mehmet Demir'in şikayetine cevap verdi."

    scrubbed = pilot._scrub_reported_names(text, ["Mehmet Demir"])

    assert "Mehmet" not in scrubbed
    assert scrubbed.count("[KİŞİ ADI]") == 2


def test_scrub_reported_names_handles_turkish_possessive_suffix():
    text = "Ayşe Yılmaz'ın dilekçesi incelendi."

    scrubbed = pilot._scrub_reported_names(text, ["Ayşe Yılmaz"])

    assert "Ayşe" not in scrubbed
    assert scrubbed == "[KİŞİ ADI] dilekçesi incelendi."


def test_scrub_reported_names_ignores_names_shorter_than_two_characters():
    text = "A harfiyle başlayan bir cümle."

    scrubbed = pilot._scrub_reported_names(text, ["A", ""])

    assert scrubbed == text
