"""Build evaluation/datasets/evrak.jsonl, the Görev 1 gold set.

Merges two sources into one JSONL file, `evaluation.harness.evrak_suite`'s
gold set:

  - `datasets/sample/evrak_*.json` (12 synthetic documents, category
    `sentetik`): each carries a hand-written `expected_fields` dict, an
    independent ground truth written when the corpus was created -- not
    derived from any parser -- so it can score field-extraction accuracy
    (bullet 3) without circularity.
  - `datasets/resmi_yazisma/ocr_ground_truth.json` (23 hand-labelled real
    scans, category `gercek_tarama`): carries `document_type` and
    `expected_missing_fields`, hand-labelled by reading each entry's
    `clean_text` against `REQUIRED_FIELD_RULES` -- see that file's own
    `_meta.gorev1_labelling` for the full methodology. Deliberately carries
    **no** `expected_fields`: an independently hand-transcribed exact-value
    dict for 23 real documents was out of scope for this pass, and deriving
    one by running `parse_labelled_fields(clean_text)` (the pattern
    `scripts/evaluate_ocr_real.py` uses) would make bullet 3's score on
    these rows tautological -- it would compare the parser against its own
    output. `evrak_suite.py` therefore only scores bullets 1 (OCR routing)
    and 4 (missing-field detection) on `gercek_tarama` rows; bullet 3 stays
    scored on `sentetik` rows only. Real-corpus field-extraction accuracy is
    already covered separately by `scripts/evaluate_ocr_real.py`, which
    measures a different, legitimate question (does OCR degrade recovery
    relative to a perfect transcription), not this suite's question (does
    the parser get fields right given known-good text).

Both sources' underlying PDF files are referenced by path, not embedded --
`evrak_suite.py`'s bullet-1 check reads bytes from disk at run time via
`pdf_path`, mirroring how `evaluate_ocr_real.py` reads the same real PDFs
for its own OCR-engine comparison.

Usage:
    python scripts/build_evrak_eval_set.py
"""

import glob
import json
import os

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
SAMPLE_DIR = os.path.join(REPO_ROOT, "datasets", "sample")
REAL_GROUND_TRUTH = os.path.join(REPO_ROOT, "datasets", "resmi_yazisma", "ocr_ground_truth.json")
REAL_PDF_DIR = os.path.join(
    REPO_ROOT, "datasets", "resmi_yazisma", "00_gelen_kaynaklar", "cevap_yazisi"
)
OUTPUT_PATH = os.path.join(REPO_ROOT, "evaluation", "datasets", "evrak.jsonl")

#: Relative to REPO_ROOT, so the JSONL is portable across host/container paths
#: the same way `evaluation.harness.runner.REPO_ROOT` resolves from the file
#: rather than the working directory.
_SAMPLE_PDF_REL = os.path.join("datasets", "sample")
_REAL_PDF_REL = os.path.join("datasets", "resmi_yazisma", "00_gelen_kaynaklar", "cevap_yazisi")


def _synthetic_rows() -> list[dict]:
    rows = []
    for json_path in sorted(glob.glob(os.path.join(SAMPLE_DIR, "evrak_*.json"))):
        with open(json_path, encoding="utf-8") as handle:
            truth = json.load(handle)
        text_path = json_path.replace(".json", ".txt")
        with open(text_path, encoding="utf-8") as handle:
            text = handle.read()
        pdf_name = os.path.basename(json_path).replace(".json", ".pdf")

        rows.append(
            {
                "id": truth["id"],
                "category": "sentetik",
                "document_type": truth["document_type"],
                "text": text,
                "pdf_path": os.path.join(_SAMPLE_PDF_REL, pdf_name),
                "scanned": bool(truth.get("scanned", False)),
                "expected": {
                    "document_type": truth["document_type"],
                    "scanned": bool(truth.get("scanned", False)),
                    "expected_fields": truth["expected_fields"],
                    "expected_missing_fields": truth["expected_missing_fields"],
                },
            }
        )
    return rows


def _real_rows() -> list[dict]:
    with open(REAL_GROUND_TRUTH, encoding="utf-8") as handle:
        ground_truth = json.load(handle)

    rows = []
    for file_name, entry in ground_truth.items():
        if file_name == "_meta":
            continue
        rows.append(
            {
                "id": file_name.split("_", 1)[0],  # e.g. "CY-001"
                "category": "gercek_tarama",
                "document_type": entry["document_type"],
                "text": entry["clean_text"],
                "pdf_path": os.path.join(_REAL_PDF_REL, file_name),
                # Every entry in this file is a real scan by construction --
                # it lives under 00_gelen_kaynaklar, the scanned-source
                # directory, unlike datasets/sample's born-digital PDFs.
                "scanned": True,
                "expected": {
                    "document_type": entry["document_type"],
                    "scanned": True,
                    # No expected_fields -- see this module's own docstring.
                    "expected_fields": None,
                    "expected_missing_fields": entry["expected_missing_fields"],
                },
            }
        )
    return rows


def main() -> None:
    rows = _synthetic_rows() + _real_rows()

    missing_pdfs = [
        row["pdf_path"]
        for row in rows
        if not os.path.isfile(os.path.join(REPO_ROOT, row["pdf_path"]))
    ]
    if missing_pdfs:
        raise SystemExit(f"HATA: PDF bulunamadı: {missing_pdfs}")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    sentetik = sum(1 for row in rows if row["category"] == "sentetik")
    gercek = sum(1 for row in rows if row["category"] == "gercek_tarama")
    print(f"Wrote {len(rows)} case(s) to {OUTPUT_PATH} ({sentetik} sentetik, {gercek} gerçek tarama).")


if __name__ == "__main__":
    main()
