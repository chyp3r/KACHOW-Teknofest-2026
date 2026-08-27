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


def test_target_decisions_keys_are_a_subset_of_allowed_decisions():
    """Guards against re-introducing an invalid decision key (this is
    exactly how ``itiraz`` ended up as a decision value in the first pilot
    run) -- the module already asserts this at import time, this test
    documents and pins that behaviour."""
    assert pilot.TARGET_DECISIONS.keys() <= pilot.ALLOWED_DECISIONS


def test_incoming_type_itiraz_constant_is_not_a_decision():
    assert pilot.INCOMING_TYPE_ITIRAZ not in pilot.ALLOWED_DECISIONS
    assert pilot.INCOMING_TYPE_ITIRAZ == "itiraz"


def test_case_id_is_deterministic_and_encodes_the_decision():
    assert pilot._case_id("tam_kabul", 3) == "GKC-PILOT-TAM_KABUL-003"
    assert pilot._case_id("tam_kabul", 3) == pilot._case_id("tam_kabul", 3)


@pytest.mark.parametrize("decision", sorted(pilot.ALLOWED_DECISIONS))
def test_case_id_accepts_every_allowed_decision(decision):
    case_id = pilot._case_id(decision, 1)
    assert case_id.startswith("GKC-PILOT-")
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
