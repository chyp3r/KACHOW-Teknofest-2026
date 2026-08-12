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
import json
import os
import re
import sys
from typing import Any, Iterator

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.ai.guardrails.pii import find_pii  # noqa: E402

CORPUS_ROOT = os.path.join(os.path.dirname(__file__), "..", "datasets", "resmi_yazisma")
GELEN_KAYNAKLAR_DIR = os.path.join(CORPUS_ROOT, "00_gelen_kaynaklar")
SINIFLANDIRMA_PATH = os.path.join(CORPUS_ROOT, "siniflandirma.json")
KATALOG_PATH = os.path.join(CORPUS_ROOT, "kaynak-katalogu.jsonl")
DEFAULT_OUTPUT_PATH = os.path.join(CORPUS_ROOT, "ornekler.jsonl")

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
) -> dict[str, Any]:
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
        "belge_turu": belge_turu or "",
        "text": text,
        "char_len": len(text),
        "source_path": source_path,
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
        )


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

    ordered = sorted(records.values(), key=lambda r: r["id"])

    with open(args.output, "w", encoding="utf-8") as handle:
        for record in ordered:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    by_type: dict[str, int] = {}
    for record in ordered:
        by_type[record["correspondence_type"]] = by_type.get(record["correspondence_type"], 0) + 1
    pii_hits = sum(1 for record in ordered if record["pii_flags"])

    print("=" * 60)
    print("   Resmî Yazışma Örnekleri Derleme")
    print("=" * 60)
    print(f"Yazıldı: {len(ordered)} örnek -> {args.output}")
    for correspondence_type, count in sorted(by_type.items()):
        print(f"  {correspondence_type}: {count}")
    print(f"PII bulgulu örnek sayısı: {pii_hits} (çıktıya yazılması engellenir)")
    print(f"Elenen dosya sayısı: {len(skipped)}")

    if args.report and skipped:
        print("\nElenenler:")
        for path, reason in skipped:
            print(f"  {reason:30s} {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
