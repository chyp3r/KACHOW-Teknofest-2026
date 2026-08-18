"""Tests for the deterministic QA pre-review gates."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import review_resmi_yazisma_qa as review  # noqa: E402


def test_clean_candidate_passes_agent_pre_review():
    meta = {
        "id": "X-1",
        "kategori": "cevap_yazisi",
        "baslik": "Başvuru Cevabı",
        "rag_status": "candidate",
        "kaynak_kurum": "Örnek Kurum",
    }

    assert review.review_card(meta, "Resmî cevap metni. " * 30) == []


def test_generic_mask_and_missing_rejection_reason_are_reported():
    meta = {
        "id": "X-2",
        "kategori": "cevap_yazisi",
        "baslik": "Başvuru Cevabı",
        "rag_status": "rejected",
        "kaynak_kurum": "Örnek Kurum",
    }
    findings = review.review_card(
        meta,
        "[KİŞİSEL BİLGİ] numaralı başvurunun e-postası yigit@example.com'dur.",
    )

    assert "genel_maske:[KİŞİSEL BİLGİ]" in findings
    assert "karar_gerekcesi_eksik" in findings
