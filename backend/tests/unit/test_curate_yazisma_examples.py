"""Tests for scripts/curate_yazisma_examples.py's pure curation logic.

Imported by path rather than as a package: the script lives outside the
backend app (mounted at /workspace/scripts in the backend container,
alongside /workspace/tests -- see compose.yml) since it curates a dataset
shared across the repo, not backend-specific code.
"""

import hashlib
import json
import os
import re
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
    assert record["template_family"].startswith("tpl-")
    assert record["dataset_split"] in {"retrieval", "dev", "heldout"}


def test_official_web_source_is_traceable_but_license_stays_review_required():
    record = curate._build_record(
        example_id="OFF-1",
        correspondence_type="response_letter",
        kategori="cevap_yazisi",
        niyet="ret",
        baslik="Başlık",
        kurum="Örnek Bakanlık",
        belge_turu="gercek_acik_kaynak",
        text="Başvurunun değerlendirilmesine ilişkin resmî cevap metni.",
        source_path="OFF-1.md",
        source_meta={
            "kaynak_url": "https://ornek.gov.tr/belge.pdf",
            "dogrulama": "acik_kaynaktan_kazindi",
        },
    )

    assert record["source_origin"] == "official_web_pending_review"
    assert record["source_url"] == "https://ornek.gov.tr/belge.pdf"
    assert record["license_status"] == "usage_review_required"


def test_same_source_group_never_leaks_between_dataset_splits():
    common = {
        "example_id": "X-5",
        "correspondence_type": "cover_letter",
        "kategori": "ust_yazi",
        "niyet": "iletim",
        "baslik": "Başlık",
        "kurum": "Kurum",
        "belge_turu": "gercek_acik_kaynak",
        "source_path": "X-5.md",
        "source_meta": {"kaynak_url": "https://ornek.gov.tr/ayni-kaynak.pdf"},
    }
    first = curate._build_record(text="Birinci belge metni.", **common)
    second = curate._build_record(text="Tamamen farklı ikinci belge metni.", **common)

    assert first["source_group"] == second["source_group"]
    assert first["dataset_split"] == second["dataset_split"]


def test_template_equivalent_records_keep_one_deterministic_representative():
    records = [
        {"id": "B-2", "template_family": "tpl-same", "source_path": "B-2.md"},
        {"id": "A-1", "template_family": "tpl-same", "source_path": "A-1.md"},
        {"id": "C-3", "template_family": "tpl-other", "source_path": "C-3.md"},
    ]
    skipped: list[tuple[str, str]] = []

    unique = curate._deduplicate_template_families(records, skipped)

    assert [record["id"] for record in unique] == ["A-1", "C-3"]
    assert skipped == [("B-2.md", "duplicate_template_family")]


def test_analysis_separates_real_and_synthetic_counts():
    base = {
        "id": "X-ANALYSIS",
        "correspondence_type": "response_letter",
        "niyet": "ret",
        "dataset_split": "retrieval",
        "kurum": "Kurum",
        "source_institution": "Kurum",
        "template_family": "tpl-1",
        "baslik": "Başlık",
        "belge_turu": "örnek",
        "source_verification": "doğrulandı",
        "text": "Resmî cevap metni.",
        "pii_flags": [],
        "source_url": "",
        "source_sha256": "abc",
        "license_status": "usage_review_required",
    }
    official = {**base, "source_origin": "official_verified_local"}
    synthetic = {
        **base,
        "template_family": "tpl-2",
        "source_origin": "synthetic",
        "license_status": "project_internal",
    }

    analysis = curate._analysis([official, synthetic])

    assert analysis["real_or_official_count"] == 1
    assert analysis["real_or_official_ratio"] == 0.5
    assert analysis["response_real_count_by_intent"] == {"ret": 1}


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


# --- Shipped split files -----------------------------------------------------
#
# The unit tests above pin the pure split *function*. These pin the artefacts
# actually committed to the repo, which is what an evaluation run reads. A
# leak here silently inflates every dev/heldout score, so it is checked on the
# real files rather than on a constructed fixture.


def _load_shipped_splits() -> dict[str, list[dict]]:
    paths = {
        "retrieval": curate.DEFAULT_OUTPUT_PATH,
        "dev": curate.DEV_EXAMPLES_PATH,
        "heldout": curate.HELDOUT_EXAMPLES_PATH,
    }
    splits: dict[str, list[dict]] = {}
    for split, path in paths.items():
        if not os.path.exists(path):
            pytest.skip(f"Split dosyası üretilmemiş: {path}")
        with open(path, encoding="utf-8") as handle:
            splits[split] = [json.loads(line) for line in handle if line.strip()]
    return splits


def _normalized_text(value: str) -> str:
    """Collapse placeholders and digits so near copies hash identically."""
    collapsed = re.sub(r"\[[^\]\n]{1,40}\]", " ", value or "")
    collapsed = re.sub(r"\d+", "0", collapsed)
    collapsed = re.sub(r"[^\w]+", " ", collapsed.casefold(), flags=re.UNICODE)
    return " ".join(collapsed.split())


@pytest.mark.parametrize(
    "field", ["source_group", "template_family", "source_sha256", "source_path"]
)
def test_shipped_splits_share_no_source_identity(field):
    splits = _load_shipped_splits()

    owner: dict[str, str] = {}
    collisions: list[tuple[str, str, str]] = []
    for split, records in splits.items():
        for record in records:
            value = record.get(field)
            if not value:
                continue
            previous = owner.setdefault(value, split)
            if previous != split:
                collisions.append((field, value, f"{previous}<->{split}"))

    assert not collisions, collisions[:10]


def test_shipped_splits_share_no_near_duplicate_body():
    splits = _load_shipped_splits()

    owner: dict[str, str] = {}
    collisions: list[tuple[str, str]] = []
    for split, records in splits.items():
        for record in records:
            digest = hashlib.sha256(
                _normalized_text(record.get("text", "")).encode("utf-8")
            ).hexdigest()
            if not record.get("text"):
                continue
            previous = owner.setdefault(digest, split)
            if previous != split:
                collisions.append((record.get("id", ""), f"{previous}<->{split}"))

    assert not collisions, collisions[:10]


def test_shipped_splits_carry_no_pii_flag_and_no_split_label_drift():
    splits = _load_shipped_splits()

    for split, records in splits.items():
        assert records, f"{split} boş"
        for record in records:
            assert record["dataset_split"] == split, record.get("id")
            assert not record["pii_flags"], (record.get("id"), record["pii_flags"])
