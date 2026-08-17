"""Curate datasets/resmi_yazisma into a reviewable few-shot example JSONL.

Reads full-text official letters from two places in the corpus:

1. ``00_gelen_kaynaklar/{ust_yazi,cevap_yazisi,bilgilendirme_metni,
   diger_resmi_yazisma}/*.md`` -- the primary pool. Each file's own front
   matter rarely carries a curated ``niyet``, so it is joined against
   ``kaynak-katalogu.jsonl`` by ``id`` (covers 873/873 non-dilekce records).
2. The numbered taxonomy directories (``0[1-4]_*/*/*.md``), including cards
   whose PDF/HTML/Word source has been converted to full Markdown.
3. ``00_gelen_kaynaklar/pdf/*.md`` -- same-stem cards generated for the
   simulation PDFs that have no numbered catalog card.

``dilekce/`` is excluded: it holds incoming petitions, not the outgoing
official letters this system drafts, so indexing it would teach the wrong
register.  Only Markdown is read; source binaries stay as provenance.

Usage:
    python scripts/curate_yazisma_examples.py
    python scripts/curate_yazisma_examples.py --report
"""

import argparse
import glob
import hashlib
import json
import os
import re
import sys
from collections import Counter
from typing import Any, Iterator
from urllib.parse import urlparse

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.ai.guardrails.pii import find_pii  # noqa: E402

CORPUS_ROOT = os.path.join(os.path.dirname(__file__), "..", "datasets", "resmi_yazisma")
GELEN_KAYNAKLAR_DIR = os.path.join(CORPUS_ROOT, "00_gelen_kaynaklar")
SINIFLANDIRMA_PATH = os.path.join(CORPUS_ROOT, "siniflandirma.json")
KATALOG_PATH = os.path.join(CORPUS_ROOT, "kaynak-katalogu.jsonl")
DEFAULT_OUTPUT_PATH = os.path.join(CORPUS_ROOT, "ornekler.jsonl")
ALL_EXAMPLES_PATH = os.path.join(CORPUS_ROOT, "ornekler-tumu.jsonl")
DEV_EXAMPLES_PATH = os.path.join(CORPUS_ROOT, "ornekler-dev.jsonl")
HELDOUT_EXAMPLES_PATH = os.path.join(CORPUS_ROOT, "ornekler-heldout.jsonl")
ANALYSIS_PATH = os.path.join(CORPUS_ROOT, "rag-veri-analizi.json")
ANALYSIS_MD_PATH = os.path.join(CORPUS_ROOT, "RAG_VERI_ANALIZI.md")

RELEVANT_FOLDERS = ("ust_yazi", "cevap_yazisi", "bilgilendirme_metni", "diger_resmi_yazisma")

MIN_CHARS = 250
INFORMATION_NOTICE_MIN_CHARS = 160
MAX_CHARS = 6000
INDEXABLE_RAG_STATUSES = {"candidate", "approved"}
ADDRESS_REPORT_CONFIDENCE_FLOOR = 0.8

#: Numbered-dir stub cards carry this exact sentence when the real text lives
#: only in an external PDF/HTML, not in the card itself.
STUB_MARKER = "Metin kartta yeniden üretilmemiştir"

_NUMERIC_PREFIX = re.compile(r"^\d+_")
_PLACEHOLDER = re.compile(r"\[[^\]\n]{2,60}\]")
_DATE_OR_NUMBER = re.compile(r"\b(?:\d{1,4}[./-]){1,2}\d{1,4}\b|\b\d+(?:[.,]\d+)?\b")
_OFFICIAL_HOST_SUFFIXES = (".gov.tr", ".edu.tr", ".bel.tr", ".k12.tr")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Split a card into its front matter and body text.

    Parsed by hand (first-colon split per line) rather than with a YAML
    library: several ``baslik`` values embed an unescaped colon (e.g. "Karar
    No: 2026/33"), which is invalid YAML mapping syntax and would otherwise
    make ``yaml.safe_load`` silently drop the whole front matter -- and with
    it the ``id`` every downstream lookup depends on.
    """
    if not text.startswith("---"):
        return {}, text.strip()
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text.strip()
    meta: dict[str, Any] = {}
    for line in text[3:end].splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        meta[key.strip()] = value
    body = text[end + 4:].strip()
    return meta, body


def _load_folder_to_type() -> dict[str, str]:
    """Map a corpus folder name to its ``correspondence_type`` value.

    Derived from ``siniflandirma.json`` rather than hand-written, so the
    mapping cannot drift out of sync with the taxonomy file.
    """
    with open(SINIFLANDIRMA_PATH, "r", encoding="utf-8") as handle:
        taxonomy = json.load(handle)
    mapping = {}
    for correspondence_type, spec in taxonomy["primary_categories"].items():
        folder = spec["folder"].split("_", 1)[1]
        mapping[folder] = correspondence_type
    return mapping


def _load_catalog() -> dict[str, dict[str, Any]]:
    """Load kaynak-katalogu.jsonl, keyed by record id.

    This is the authoritative source of ``niyet`` for the
    ``00_gelen_kaynaklar`` pool -- most of those files carry no ``niyet`` in
    their own front matter.
    """
    catalog: dict[str, dict[str, Any]] = {}
    with open(KATALOG_PATH, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            catalog[record["id"]] = record
    return catalog


def _usable_url(value: Any) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate.startswith(("https://", "http://")) else ""


def _source_url(meta: dict[str, Any]) -> str:
    for field in ("kaynak_url", "belge_url", "url", "kaynak"):
        candidate = _usable_url(meta.get(field))
        if candidate:
            return candidate
    return ""


def _source_origin(meta: dict[str, Any], example_id: str, source_url: str) -> str:
    provenance = " ".join(
        str(meta.get(field, ""))
        for field in ("dogrulama", "belge_turu", "kaynak", "kaynak_kurum")
    ).casefold()
    if "simulasyon" in example_id.casefold() or any(
        marker in provenance for marker in ("sentetik", "otonom_script", "simulasyon")
    ):
        return "synthetic"
    if "resmi_kaynaktan_indirildi" in provenance:
        return "official_verified_local"
    hostname = (urlparse(source_url).hostname or "").removeprefix("www.").casefold()
    if hostname.endswith(_OFFICIAL_HOST_SUFFIXES):
        return "official_web_pending_review"
    if source_url:
        return "public_web_pending_review"
    return "local_source_pending_review"


def _resolve_source_file(meta: dict[str, Any]) -> str:
    candidates = (meta.get("yerel_orijinal"), meta.get("kaynak"))
    repo_root = os.path.abspath(os.path.join(CORPUS_ROOT, "..", ".."))
    for raw in candidates:
        value = str(raw or "").strip().replace("/", os.sep)
        if not value or value.startswith(("http://", "https://")):
            continue
        path = value if os.path.isabs(value) else os.path.join(CORPUS_ROOT, value)
        if not os.path.isfile(path):
            path = value if os.path.isabs(value) else os.path.join(repo_root, value)
        if os.path.isfile(path):
            return path
    return ""


def _source_hash(meta: dict[str, Any]) -> str:
    path = _resolve_source_file(meta)
    if not path:
        return ""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _template_family(correspondence_type: str, text: str) -> str:
    normalized = text.casefold()
    normalized = _PLACEHOLDER.sub("[alan]", normalized)
    normalized = _DATE_OR_NUMBER.sub("[sayi]", normalized)
    normalized = re.sub(r"https?://\S+", "[url]", normalized)
    normalized = re.sub(r"[^a-zçğıöşü\[\] ]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    digest = hashlib.sha256(f"{correspondence_type}\n{normalized}".encode("utf-8")).hexdigest()
    return f"tpl-{digest[:16]}"


def _dataset_split(source_group: str) -> str:
    bucket = int(hashlib.sha256(source_group.encode("utf-8")).hexdigest()[:8], 16) % 100
    if bucket < 80:
        return "retrieval"
    if bucket < 90:
        return "dev"
    return "heldout"


def _build_record(
    *,
    example_id: str,
    correspondence_type: str,
    kategori: str,
    niyet: str,
    baslik: str,
    kurum: str,
    belge_turu: str,
    text: str,
    source_path: str,
    source_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_meta = source_meta or {}
    source_url = _source_url(source_meta)
    source_sha256 = _source_hash(source_meta)
    template_family = _template_family(correspondence_type, text)
    source_group = source_sha256 or source_url or template_family
    origin = _source_origin(source_meta, example_id, source_url)
    pii_flags = [
        {"kind": finding.kind, "confidence": finding.confidence, "preview": finding.preview}
        for finding in find_pii(text)
        if finding.kind != "adres" or finding.confidence >= ADDRESS_REPORT_CONFIDENCE_FLOOR
    ]
    return {
        "id": example_id,
        "correspondence_type": correspondence_type,
        "kategori": kategori,
        "niyet": niyet or "genel",
        "baslik": baslik or "",
        "kurum": kurum or "",
        "source_institution": source_meta.get("kaynak_kurum") or kurum or "",
        "belge_turu": belge_turu or "",
        "text": text,
        "char_len": len(text),
        "source_path": source_path,
        "source_url": source_url,
        "source_origin": origin,
        "source_verification": source_meta.get("dogrulama", "pending_review"),
        "source_sha256": source_sha256,
        "license_status": (
            "project_internal" if origin == "synthetic" else "usage_review_required"
        ),
        "template_family": template_family,
        "source_group": hashlib.sha256(source_group.encode("utf-8")).hexdigest()[:16],
        "dataset_split": _dataset_split(source_group),
        "pii_flags": pii_flags,
    }


def _skip_reason(meta: dict[str, Any], body: str) -> str:
    """Return why a card must not enter RAG, or an empty string."""
    status = meta.get("rag_status", "candidate")
    if status not in INDEXABLE_RAG_STATUSES:
        return f"rag_status={status}"
    if STUB_MARKER in body or not meta.get("id"):
        return "stub_or_no_id"
    minimum = INFORMATION_NOTICE_MIN_CHARS if meta.get("kategori") == "bilgilendirme_metni" else MIN_CHARS
    if not (minimum <= len(body) <= MAX_CHARS):
        return f"length={len(body)}"
    return ""


def _pii_reason(record: dict[str, Any]) -> str:
    """Return a fail-closed reason when a candidate still contains PII."""
    if record["pii_flags"]:
        kinds = sorted({finding["kind"] for finding in record["pii_flags"]})
        return f"pii={','.join(kinds)}"
    return ""


def _add_record(
    records: dict[str, dict[str, Any]],
    record: dict[str, Any],
    skipped: list[tuple[str, str]],
    *,
    overwrite: bool,
) -> None:
    """Add one record only after the final PII gate has passed."""
    reason = _pii_reason(record)
    if reason:
        skipped.append((record["source_path"], reason))
        return
    if overwrite:
        records[record["id"]] = record
    else:
        records.setdefault(record["id"], record)


def _iter_gelen_kaynaklar_examples(
    folder_to_type: dict[str, str],
    catalog: dict[str, dict[str, Any]],
    skipped: list[tuple[str, str]],
) -> Iterator[dict[str, Any]]:
    for folder in RELEVANT_FOLDERS:
        correspondence_type = folder_to_type[folder]
        pattern = os.path.join(GELEN_KAYNAKLAR_DIR, folder, "*.md")
        for path in sorted(glob.glob(pattern)):
            meta, body = _split_front_matter(_read(path))
            example_id = meta.get("id")
            reason = _skip_reason(meta, body)
            if reason:
                skipped.append((path, reason))
                continue
            catalog_entry = catalog.get(example_id, {})
            yield _build_record(
                example_id=example_id,
                correspondence_type=correspondence_type,
                kategori=meta.get("kategori", folder),
                niyet=catalog_entry.get("niyet"),
                baslik=catalog_entry.get("baslik") or meta.get("baslik"),
                kurum=meta.get("kurum") or catalog_entry.get("kurum"),
                belge_turu=meta.get("belge_turu", ""),
                text=body,
                source_path=os.path.relpath(path, CORPUS_ROOT),
                source_meta={**catalog_entry, **meta},
            )


def _iter_numbered_dir_examples(
    folder_to_type: dict[str, str],
    skipped: list[tuple[str, str]],
) -> Iterator[dict[str, Any]]:
    pattern = os.path.join(CORPUS_ROOT, "0[1-4]_*", "*", "*.md")
    for path in sorted(glob.glob(pattern)):
        if os.path.basename(path).startswith("_"):
            continue
        meta, body = _split_front_matter(_read(path))
        example_id = meta.get("id")
        reason = _skip_reason(meta, body)
        if reason:
            skipped.append((path, reason))
            continue
        kategori = meta.get("kategori", "")
        correspondence_type = folder_to_type.get(kategori)
        if correspondence_type is None:
            skipped.append((path, f"unknown_kategori={kategori}"))
            continue
        niyet = _NUMERIC_PREFIX.sub("", meta.get("niyet") or "genel")
        yield _build_record(
            example_id=example_id,
            correspondence_type=correspondence_type,
            kategori=kategori,
            niyet=niyet,
            baslik=meta.get("baslik", ""),
            kurum=meta.get("kurum", ""),
            belge_turu=meta.get("belge_turu", ""),
            text=body,
            source_path=os.path.relpath(path, CORPUS_ROOT),
            source_meta=meta,
        )


def _iter_generated_pdf_examples(
    folder_to_type: dict[str, str],
    catalog: dict[str, dict[str, Any]],
    skipped: list[tuple[str, str]],
) -> Iterator[dict[str, Any]]:
    """Yield same-stem Markdown cards created beside uncatalogued PDFs."""
    pattern = os.path.join(GELEN_KAYNAKLAR_DIR, "pdf", "*.md")
    for path in sorted(glob.glob(pattern)):
        meta, body = _split_front_matter(_read(path))
        reason = _skip_reason(meta, body)
        if reason:
            skipped.append((path, reason))
            continue
        kategori = meta.get("kategori", "")
        correspondence_type = folder_to_type.get(kategori)
        if correspondence_type is None:
            skipped.append((path, f"unknown_kategori={kategori}"))
            continue
        example_id = meta["id"]
        catalog_entry = catalog.get(example_id, {})
        yield _build_record(
            example_id=example_id,
            correspondence_type=correspondence_type,
            kategori=kategori,
            niyet=meta.get("niyet") or catalog_entry.get("niyet"),
            baslik=meta.get("baslik") or catalog_entry.get("baslik"),
            kurum=meta.get("kurum") or catalog_entry.get("kurum"),
            belge_turu=meta.get("belge_turu", ""),
            text=body,
            source_path=os.path.relpath(path, CORPUS_ROOT),
            source_meta={**catalog_entry, **meta},
        )


def _write_jsonl(path: str, records: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _deduplicate_template_families(
    records: list[dict[str, Any]], skipped: list[tuple[str, str]]
) -> list[dict[str, Any]]:
    """Keep one deterministic representative of each normalized template."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda item: item["id"]):
        family = record["template_family"]
        if family in seen:
            skipped.append((record["source_path"], "duplicate_template_family"))
            continue
        seen.add(family)
        unique.append(record)
    return unique


def _analysis(records: list[dict[str, Any]]) -> dict[str, Any]:
    origin = Counter(record["source_origin"] for record in records)
    split = Counter(record["dataset_split"] for record in records)
    correspondence = Counter(record["correspondence_type"] for record in records)
    institutions = Counter(record["source_institution"] or "Bilinmiyor" for record in records)
    template_sizes = Counter(record["template_family"] for record in records)
    duplicate_families = {key: value for key, value in template_sizes.items() if value > 1}
    missing = Counter()
    for record in records:
        for field in ("baslik", "kurum", "belge_turu", "source_verification"):
            if not str(record.get(field, "")).strip():
                missing[field] += 1
    type_origin: dict[str, Counter[str]] = {}
    intent_origin: dict[str, dict[str, Counter[str]]] = {}
    split_origin: dict[str, Counter[str]] = {}
    for record in records:
        kind = record["correspondence_type"]
        intent = record["niyet"]
        record_origin = record["source_origin"]
        type_origin.setdefault(kind, Counter())[record_origin] += 1
        intent_origin.setdefault(kind, {}).setdefault(intent, Counter())[record_origin] += 1
        split_origin.setdefault(record["dataset_split"], Counter())[record_origin] += 1
    real_by_type = {
        kind: sum(count for key, count in counts.items() if key != "synthetic")
        for kind, counts in type_origin.items()
    }
    real_total = sum(count for key, count in origin.items() if key != "synthetic")
    response_real_by_intent = {
        intent: sum(count for key, count in counts.items() if key != "synthetic")
        for intent, counts in intent_origin.get("response_letter", {}).items()
    }
    baseline = {
        "total_curated": 384,
        "real_or_official": 236,
        "synthetic": 148,
        "generic_person_placeholder_count": 58,
        "missing_metadata_records": 32,
        "simulation_records_in_production": 32,
        "records_in_duplicate_template_families": 9,
        "separate_dev_heldout_records": 0,
    }
    current = {
        "total_curated": len(records),
        "real_or_official": real_total,
        "synthetic": origin.get("synthetic", 0),
        "generic_person_placeholder_count": sum(
            record["text"].count("[KİŞİSEL BİLGİ]") for record in records
        ),
        "missing_metadata_records": sum(missing.values()),
        "simulation_records_in_production": sum(
            "SIMULASYON" in record["id"].upper() for record in records
        ),
        "records_in_duplicate_template_families": sum(duplicate_families.values()),
        "separate_dev_heldout_records": split.get("dev", 0) + split.get("heldout", 0),
    }
    return {
        "schema_version": 1,
        "total_curated": len(records),
        "split_distribution": dict(sorted(split.items())),
        "origin_distribution": dict(sorted(origin.items())),
        "real_or_official_count": real_total,
        "real_or_official_ratio": round(real_total / len(records), 4) if records else 0,
        "synthetic_ratio": round(origin.get("synthetic", 0) / len(records), 4) if records else 0,
        "type_origin_distribution": {
            kind: dict(sorted(counts.items())) for kind, counts in sorted(type_origin.items())
        },
        "split_origin_distribution": {
            name: dict(sorted(counts.items())) for name, counts in sorted(split_origin.items())
        },
        "real_count_by_type": dict(sorted(real_by_type.items())),
        "real_gap_to_100_by_type": {
            kind: max(0, 100 - count) for kind, count in sorted(real_by_type.items())
        },
        "response_real_count_by_intent": dict(sorted(response_real_by_intent.items())),
        "correspondence_type_distribution": dict(sorted(correspondence.items())),
        "institution_distribution": dict(institutions.most_common()),
        "missing_metadata": dict(sorted(missing.items())),
        "generic_person_placeholder_count": sum(
            record["text"].count("[KİŞİSEL BİLGİ]") for record in records
        ),
        "legacy_deleted_placeholder_count": sum(
            record["text"].count("[SİLİNMİŞTİR]") for record in records
        ),
        "pii_flagged_count": sum(bool(record["pii_flags"]) for record in records),
        "unique_template_families": len(template_sizes),
        "duplicate_template_families": len(duplicate_families),
        "records_in_duplicate_template_families": sum(duplicate_families.values()),
        "records_with_source_url": sum(bool(record["source_url"]) for record in records),
        "records_with_source_sha256": sum(bool(record["source_sha256"]) for record in records),
        "license_status_distribution": dict(
            sorted(Counter(record["license_status"] for record in records).items())
        ),
        "before_after": {"before": baseline, "after": current},
    }


def _write_analysis(records: list[dict[str, Any]]) -> dict[str, Any]:
    analysis = _analysis(records)
    with open(ANALYSIS_PATH, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(analysis, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    origin_rows = "\n".join(
        f"| `{key}` | {value} |" for key, value in analysis["origin_distribution"].items()
    )
    split_rows = "\n".join(
        f"| `{key}` | {value} |" for key, value in analysis["split_distribution"].items()
    )
    type_rows = "\n".join(
        f"| `{kind}` | {analysis['real_count_by_type'][kind]} | "
        f"{analysis['real_gap_to_100_by_type'][kind]} |"
        for kind in analysis["real_count_by_type"]
    )
    before_after_rows = "\n".join(
        f"| `{metric}` | {analysis['before_after']['before'][metric]} | "
        f"{analysis['before_after']['after'][metric]} |"
        for metric in analysis["before_after"]["before"]
    )
    markdown = f"""# RAG Veri Analizi

> Bu dosya `scripts/curate_yazisma_examples.py` tarafından deterministik olarak üretilir.

## Kalite özeti

- Kalite kapısını geçen toplam örnek: **{analysis['total_curated']}**
- Tekil şablon ailesi: **{analysis['unique_template_families']}**
- Birden fazla kayıt taşıyan şablon ailesi: **{analysis['duplicate_template_families']}**
- Yüksek güvenli PII bulgusu: **{analysis['pii_flagged_count']}**
- Genel `[KİŞİSEL BİLGİ]` maskesi: **{analysis['generic_person_placeholder_count']}**
- Eski `[SİLİNMİŞTİR]` maskesi: **{analysis['legacy_deleted_placeholder_count']}**
- Doğrudan kaynak URL'si olan örnek: **{analysis['records_with_source_url']}**
- Yerel kaynak SHA-256 izi olan örnek: **{analysis['records_with_source_sha256']}**
- Gerçek/resmî kaynaklı örnek oranı: **%{analysis['real_or_official_ratio'] * 100:.1f}**
- Sentetik örnek oranı: **%{analysis['synthetic_ratio'] * 100:.1f}**

## Kaynak kökeni

| Köken | Kayıt |
|---|---:|
{origin_rows}

`pending_review` kökenleri kaynağın resmî alan adında veya yerel arşivde olduğunu,
ancak kullanım/lisans kararının henüz insan tarafından onaylanmadığını belirtir.

## Sızıntısız veri ayrımı

| Ayrım | Kayıt |
|---|---:|
{split_rows}

Ayrım tek tek kayıtlara göre değil, kaynak dosya/URL veya normalleştirilmiş
şablon ailesine göre yapılır. Aynı kaynak ya da aynı şablon retrieval ve ölçüm
kümelerine bölünemez.

## Yazı türü başına gerçek veri açığı

| Yazı türü | Gerçek/resmî | 100 hedefi için açık |
|---|---:|---:|
{type_rows}

Bu hedef yalnız kayıt sayısı değildir. Aynı şablon ailesinin farklı değerlerle
çoğaltılması sayıyı artırmaz.

## Önce / sonra

| Ölçüt | Önce | Sonra |
|---|---:|---:|
{before_after_rows}

Önce değerleri 2026-08-17 tarihli yol haritası öncesi denetim anlık görüntüsüdür.
Toplamın azalması veri kaybı değil; 32 OCR simülasyonunun üretimden çıkarılması ve
5 şablon tekrarının tekilleştirilmesidir.
"""
    with open(ANALYSIS_MD_PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(markdown)
    return analysis


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="resmi_yazisma korpusunu few-shot örnek JSONL'ine derle."
    )
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT_PATH, help="Çıktı JSONL dosyası."
    )
    parser.add_argument(
        "--report", action="store_true", help="Elenen dosyaları sebepleriyle listele."
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    folder_to_type = _load_folder_to_type()
    catalog = _load_catalog()

    skipped: list[tuple[str, str]] = []
    records: dict[str, dict[str, Any]] = {}
    for record in _iter_gelen_kaynaklar_examples(folder_to_type, catalog, skipped):
        _add_record(records, record, skipped, overwrite=True)
    for record in _iter_numbered_dir_examples(folder_to_type, skipped):
        _add_record(records, record, skipped, overwrite=False)
    for record in _iter_generated_pdf_examples(folder_to_type, catalog, skipped):
        _add_record(records, record, skipped, overwrite=False)

    ordered = _deduplicate_template_families(list(records.values()), skipped)
    by_split = {
        name: [record for record in ordered if record["dataset_split"] == name]
        for name in ("retrieval", "dev", "heldout")
    }
    _write_jsonl(ALL_EXAMPLES_PATH, ordered)
    _write_jsonl(args.output, by_split["retrieval"])
    _write_jsonl(DEV_EXAMPLES_PATH, by_split["dev"])
    _write_jsonl(HELDOUT_EXAMPLES_PATH, by_split["heldout"])
    analysis = _write_analysis(ordered)

    by_type: dict[str, int] = {}
    for record in by_split["retrieval"]:
        by_type[record["correspondence_type"]] = by_type.get(record["correspondence_type"], 0) + 1
    pii_hits = sum(1 for record in ordered if record["pii_flags"])

    print("=" * 60)
    print("   Resmî Yazışma Örnekleri Derleme")
    print("=" * 60)
    print(f"Kalite kapısını geçen: {len(ordered)} örnek -> {ALL_EXAMPLES_PATH}")
    print(f"Retrieval: {len(by_split['retrieval'])} örnek -> {args.output}")
    print(f"Dev: {len(by_split['dev'])} örnek -> {DEV_EXAMPLES_PATH}")
    print(f"Heldout: {len(by_split['heldout'])} örnek -> {HELDOUT_EXAMPLES_PATH}")
    for correspondence_type, count in sorted(by_type.items()):
        print(f"  {correspondence_type}: {count}")
    print(f"PII bulgulu örnek sayısı: {pii_hits} (çıktıya yazılması engellenir)")
    print(f"Tekil şablon ailesi: {analysis['unique_template_families']}")
    print(f"Elenen dosya sayısı: {len(skipped)}")

    if args.report and skipped:
        print("\nElenenler:")
        for path, reason in skipped:
            print(f"  {reason:30s} {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
