"""Tests for scripts/curate_yazisma_examples.py's pure curation logic.

Imported by path rather than as a package: the script lives outside the
backend app (mounted at /workspace/scripts in the backend container,
alongside /workspace/tests -- see compose.yml) since it curates a dataset
shared across the repo, not backend-specific code.
"""

import json
import os
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts")
)
import curate_yazisma_examples as curate  # noqa: E402


# --- Front matter parsing ----------------------------------------------------
#
# The real corpus's `baslik` values routinely embed an unescaped colon (e.g.
# "Karar No: 2026/33"), which is invalid YAML mapping syntax. A YAML-based
# parser silently drops the whole front matter -- and with it the `id` every
# downstream lookup depends on -- which is exactly what happened on the first
# curation run (926 examples became far fewer once this was fixed). These
# tests pin the hand-rolled, first-colon-only parser that replaced it.


def test_a_value_with_an_embedded_colon_is_still_parsed():
    text = (
        "---\n"
        "id: BEL-001\n"
        "baslik: Salihli Belediyesi Kararı (Karar No: 2026/33)\n"
        "---\n"
        "Gövde metni."
    )
    meta, body = curate._split_front_matter(text)

    assert meta["id"] == "BEL-001"
    assert meta["baslik"] == "Salihli Belediyesi Kararı (Karar No: 2026/33)"
    assert body == "Gövde metni."


def test_quoted_values_have_their_quotes_stripped():
    text = '---\nkurum: "Van Eğitim ve Araştırma Hastanesi"\n---\nGövde.'
    meta, _ = curate._split_front_matter(text)

    assert meta["kurum"] == "Van Eğitim ve Araştırma Hastanesi"


def test_a_file_with_no_front_matter_returns_empty_meta_and_the_full_body():
    text = "Sadece düz metin, front matter yok."
    meta, body = curate._split_front_matter(text)

    assert meta == {}
    assert body == text


def test_non_indexable_rag_status_is_skipped_before_length_checks():
    meta = {"id": "BAD-1", "kategori": "cevap_yazisi", "rag_status": "rejected"}

    assert curate._skip_reason(meta, "Uzun metin. " * 100) == "rag_status=rejected"


def test_short_but_valid_information_notice_has_a_category_specific_limit():
    meta = {"id": "BM-1", "kategori": "bilgilendirme_metni", "rag_status": "candidate"}
    body = "Planlı kesinti nedeniyle sistem kullanılamayacaktır. " * 4

    assert 160 <= len(body) < curate.MIN_CHARS
    assert curate._skip_reason(meta, body) == ""


def test_a_line_without_a_colon_inside_front_matter_is_skipped_not_raised():
    text = "---\nid: X-1\nbozuk satır\nkurum: Test Kurumu\n---\nGövde."
    meta, _ = curate._split_front_matter(text)

    assert meta == {"id": "X-1", "kurum": "Test Kurumu"}


# --- Taxonomy mapping ---------------------------------------------------------


def test_folder_to_type_mapping_matches_siniflandirma_json():
    mapping = curate._load_folder_to_type()

    assert mapping == {
        "ust_yazi": "cover_letter",
        "cevap_yazisi": "response_letter",
        "bilgilendirme_metni": "information_notice",
        "diger_resmi_yazisma": "other_official",
    }


def test_dilekce_is_not_a_relevant_folder():
    """dilekce/ holds incoming petitions, not outgoing official letters --
    including it would teach the writer the wrong register entirely."""
    assert "dilekce" not in curate.RELEVANT_FOLDERS


# --- Record building (PII pass-through) ---------------------------------------


def test_build_record_defaults_niyet_when_missing():
    record = curate._build_record(
        example_id="X-1",
        correspondence_type="cover_letter",
        kategori="ust_yazi",
        niyet="",
        baslik="Başlık",
        kurum="Kurum",
        belge_turu="gercek_acik_kaynak",
        text="Gövde metni burada, kişisel veri yok.",
        source_path="00_gelen_kaynaklar/ust_yazi/X-1.md",
    )

    assert record["niyet"] == "genel"
    assert record["pii_flags"] == []
    assert record["char_len"] == len(record["text"])


def test_build_record_surfaces_pii_findings():
    record = curate._build_record(
        example_id="X-2",
        correspondence_type="response_letter",
        kategori="cevap_yazisi",
        niyet="test",
        baslik="Başlık",
        kurum="Kurum",
        belge_turu="gercek_acik_kaynak",
        text="Başvuru sahibinin telefonu: 0532 123 45 67 numarasıdır.",
        source_path="00_gelen_kaynaklar/cevap_yazisi/X-2.md",
    )

    assert any(flag["kind"] == "telefon" for flag in record["pii_flags"])
    # A finding carries a masked preview, never the raw value.
    assert all("0532 123 45 67" not in flag["preview"] for flag in record["pii_flags"])


def test_low_confidence_address_heuristic_is_not_reported_as_actionable_pii():
    record = curate._build_record(
        example_id="X-3",
        correspondence_type="response_letter",
        kategori="cevap_yazisi",
        niyet="gorus",
        baslik="Başlık",
        kurum="Kurum",
        belge_turu="ornek",
        text="Mahalle muhtarlarına ilişkin Mahalle Muhtarlıkları Kanunu incelenmiştir.",
        source_path="X-3.md",
    )

    assert record["pii_flags"] == []


def test_pii_gate_does_not_add_a_record_to_the_output():
    record = curate._build_record(
        example_id="X-4",
        correspondence_type="response_letter",
        kategori="cevap_yazisi",
        niyet="test",
        baslik="Başlık",
        kurum="Kurum",
        belge_turu="gercek_acik_kaynak",
        text="Başvuru sahibinin telefonu 0532 123 45 67 olarak kaydedilmiştir.",
        source_path="X-4.md",
    )
    records: dict[str, dict] = {}
    skipped: list[tuple[str, str]] = []

    curate._add_record(records, record, skipped, overwrite=True)

    assert records == {}
    assert skipped == [("X-4.md", "pii=telefon")]


# --- End-to-end over a small synthetic corpus ----------------------------------


@pytest.fixture
def synthetic_corpus(tmp_path, monkeypatch):
    """A miniature corpus mirroring the real layout, with one file of each
    kind the curation walk must handle: a normal record, a stub card with no
    reproduced text, a record missing from the catalog, and a numbered-dir
    synthetic full-text card."""
    root = tmp_path / "resmi_yazisma"
    gelen = root / "00_gelen_kaynaklar" / "cevap_yazisi"
    gelen.mkdir(parents=True)

    body = "Gövde metni. " * 40  # clears MIN_CHARS
    (gelen / "OK-001.md").write_text(
        f"---\nid: OK-001\nkategori: cevap_yazisi\nkurum: Test Kurumu\n"
        f"belge_turu: gercek_acik_kaynak\n---\n{body}",
        encoding="utf-8",
    )
    (gelen / "STUB-001.md").write_text(
        "---\nid: STUB-001\nkategori: cevap_yazisi\n---\n"
        "- Yerel asıl belge: 00_gelen_kaynaklar/cevap_yazisi/STUB-001.pdf\n"
        "\nMetin kartta yeniden üretilmemiştir; gerçek içerik kaynak bağlantısındadır.",
        encoding="utf-8",
    )
    (gelen / "SHORT-001.md").write_text(
        "---\nid: SHORT-001\nkategori: cevap_yazisi\n---\nKısa.",
        encoding="utf-8",
    )

    numbered = root / "02_cevap_yazisi" / "01_istek_talep"
    numbered.mkdir(parents=True)
    (numbered / "SYN-001.md").write_text(
        f"---\nid: SYN-001\nkategori: cevap_yazisi\nniyet: 01_istek_talep\n"
        f"kurum: Sentetik Kurum\n---\n{body}",
        encoding="utf-8",
    )

    catalog_path = root / "kaynak-katalogu.jsonl"
    with open(catalog_path, "w", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"id": "OK-001", "niyet": "bilgi_edinme", "baslik": "OK Başlık", "kurum": "Katalog Kurumu"})
            + "\n"
        )

    monkeypatch.setattr(curate, "CORPUS_ROOT", str(root))
    monkeypatch.setattr(curate, "GELEN_KAYNAKLAR_DIR", str(root / "00_gelen_kaynaklar"))
    monkeypatch.setattr(curate, "KATALOG_PATH", str(catalog_path))
    return root


def test_a_normal_record_is_joined_with_its_catalog_niyet(synthetic_corpus):
    folder_to_type = {"cevap_yazisi": "response_letter"}
    catalog = curate._load_catalog()
    skipped: list[tuple[str, str]] = []

    records = list(
        curate._iter_gelen_kaynaklar_examples(
            {**folder_to_type, "ust_yazi": "cover_letter",
             "bilgilendirme_metni": "information_notice",
             "diger_resmi_yazisma": "other_official"},
            catalog,
            skipped,
        )
    )

    ok = next(r for r in records if r["id"] == "OK-001")
    assert ok["correspondence_type"] == "response_letter"
    assert ok["niyet"] == "bilgi_edinme"
    assert ok["baslik"] == "OK Başlık"


def test_a_stub_card_and_a_too_short_record_are_both_skipped(synthetic_corpus):
    catalog = curate._load_catalog()
    skipped: list[tuple[str, str]] = []

    ids = {
        r["id"]
        for r in curate._iter_gelen_kaynaklar_examples(
            {"cevap_yazisi": "response_letter", "ust_yazi": "cover_letter",
             "bilgilendirme_metni": "information_notice",
             "diger_resmi_yazisma": "other_official"},
            catalog,
            skipped,
        )
    }

    assert "STUB-001" not in ids
    assert "SHORT-001" not in ids
    skipped_ids = {path.split(os.sep)[-1] for path, _reason in skipped}
    assert "STUB-001.md" in skipped_ids
    assert "SHORT-001.md" in skipped_ids


def test_a_numbered_dir_synthetic_card_carries_its_own_niyet_without_numeric_prefix(
    synthetic_corpus,
):
    folder_to_type = {"cevap_yazisi": "response_letter"}
    skipped: list[tuple[str, str]] = []

    records = list(curate._iter_numbered_dir_examples(folder_to_type, skipped))

    syn = next(r for r in records if r["id"] == "SYN-001")
    assert syn["correspondence_type"] == "response_letter"
    assert syn["niyet"] == "istek_talep"
