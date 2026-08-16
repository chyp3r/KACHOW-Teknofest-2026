"""Measure OCR field recovery on the REAL scanned corpus, not synthetic evrak.

Sibling to `evaluate_ocr_fields.py`, which stays as the fast, reproducible
synthetic-corpus benchmark (12 degraded documents, 62 labelled fields) that
already decided deepseek-ocr as the shipped default. This script exists for a
different question: does a candidate model actually help on the real,
handwriting-and-letterhead-carrying documents this project was built to
handle, not a synthetically degraded stand-in for them.

Ground truth: `datasets/resmi_yazisma/ocr_ground_truth.json`, 15 hand-labelled
real CY-*.pdf documents (see that file's own "_meta" block for the labelling
methodology). Expected fields are derived by running each entry's
`clean_text` through the same `parse_labelled_fields()` the OCR output is
scored with -- exactly mirroring how `evaluate_ocr_fields.py` derives its own
ground truth from `datasets/sample/evrak_*.txt` ("Ground truth is the parse of
the source text, not the JSON annotation"). A field the parser cannot recover
even from a perfect transcription (e.g. `muhatap` on CY-010, whose addressee
is a named MP rather than a dative-suffixed institution) is therefore
correctly absent from `expected` and never penalises any engine.

Every engine is reached through the real `OllamaVisionExtractor` /
`TesseractExtractor` / `FallbackDocumentExtractor` classes -- no bespoke
HTTP client, no re-implementation of the extraction chain -- so a benchmark
run and a real production request exercise identical code. A transformers
model under test is expected to already be running via `scripts/ocr_sidecar.py`
on the host; this script only ever speaks Ollama's `/api/generate` contract
to whatever `--base-url` a `sidecar:` engine spec names.

Engine specs (repeatable via --engine):
    tesseract
    ollama:<model>[@<base_url>]              (default base_url = Ollama's)
    sidecar:<label>@<base_url>@<model_id>    (label is just a display name)

Two things are scored per engine, per document:
  - the RAW single-engine transcription (what the model alone produces)
  - the FULL PRODUCTION CHAIN with this engine as both a chain member and
    the header-repair step (mirrors get_document_extractor()'s own wiring),
    since header repair -- not raw full-page transcription -- is where any
    winner actually gets used.

Scoring is reported both raw-exact and whitespace/case-normalised, because a
correct value that merely differs in a trailing handwritten-annotation token
or in capitalisation should not read as a total loss (see the addressee-line
regression this same real corpus surfaced during development -- documented
in field_parser.py and this project's plan file).

Usage:
    # Baselines already reachable via the default Ollama instance:
    python scripts/evaluate_ocr_real.py \\
        --engine tesseract --engine ollama:deepseek-ocr --engine "ollama:glm-ocr:latest"

    # A transformers model under test (start the sidecar first):
    #   .venv-ocr5/bin/python scripts/ocr_sidecar.py --model zai-org/GLM-OCR
    python scripts/evaluate_ocr_real.py \\
        --engine "sidecar:glm-ocr-hf@http://127.0.0.1:11435@zai-org/GLM-OCR" \\
        --results-file scratchpad/ocr_real_results.json

Each run merges its results into --results-file (default
scratchpad/ocr_real_results.json) keyed by engine name, so separate
invocations -- one per sidecar model, since only one model fits in memory at
a time -- accumulate into one final comparison table. Pass --report-only to
skip running anything and just print the table from what has already
accumulated.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.ai.compliance import parse_labelled_fields  # noqa: E402
from app.infrastructure.extractors import (  # noqa: E402
    FallbackDocumentExtractor,
    OllamaVisionExtractor,
    OpenDataLoaderExtractor,
    PdfiumExtractor,
    PlainTextExtractor,
    TesseractExtractor,
)

CORPUS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "datasets",
    "resmi_yazisma",
    "00_gelen_kaynaklar",
    "cevap_yazisi",
)
GROUND_TRUTH_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "datasets",
    "resmi_yazisma",
    "ocr_ground_truth.json",
)
DEFAULT_RESULTS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "scratchpad", "ocr_real_results.json"
)
FIELD_KEYS = ("sayi", "tarih", "konu", "muhatap", "gonderen_kurum")
#: Collapses whitespace and case so a near-miss (an extra handwritten-
#: annotation token, a stray space) doesn't score identically to a total
#: loss -- see the module docstring.
_normalise = lambda s: re.sub(r"\s+", " ", str(s)).strip().lower()  # noqa: E731


def _load_ground_truth() -> dict:
    with open(GROUND_TRUTH_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    data.pop("_meta", None)
    return data


def _load_documents(ground_truth: dict) -> list[tuple[str, bytes, dict]]:
    """Pair each ground-truth entry with its real PDF bytes and expected fields."""
    items = []
    for name, entry in sorted(ground_truth.items()):
        path = os.path.join(CORPUS_DIR, name)
        if not os.path.isfile(path):
            sys.exit(f"HATA: {path} bulunamadı (ground truth dosyası eski olabilir).")
        with open(path, "rb") as fh:
            pdf_bytes = fh.read()
        expected = parse_labelled_fields(entry["clean_text"])
        items.append((name, pdf_bytes, {k: expected.get(k) for k in FIELD_KEYS if expected.get(k)}))
    return items


def _parse_engine_spec(spec: str):
    """Build (name, extraction_engine) from one --engine string.

    Uses '@' (never '/') as the field separator, not ':' -- an Ollama model
    name is itself colon-separated ('glm-ocr:latest', 'frob/unlimited-ocr:q8_0')
    and a base_url contains colons too ('http://host:port'), so splitting on
    ':' silently mangles either one. Found the hard way: an early version of
    this function split "ollama:glm-ocr:latest" into model='glm-ocr',
    base_url='latest', which urllib then rejected as "unknown url type" for
    the raw pass while the chain pass's header-repair step swallowed the
    identical failure silently (best-effort, matching fallback.py's own
    documented behaviour) and fell back to unrepaired Tesseract text --
    producing a result that looked like a real (if poor) glm-ocr score but
    was actually just Tesseract's own baseline in disguise.

    Returns:
        A tuple of a display name and an OllamaVisionExtractor/TesseractExtractor
        instance -- both share `extract()`, so callers don't need to branch.
    """
    if spec == "tesseract":
        return "tesseract", TesseractExtractor()
    if spec.startswith("ollama:"):
        rest = spec[len("ollama:") :]
        model, _, base_url = rest.partition("@")
        return f"ollama:{model}", OllamaVisionExtractor(model=model, base_url=base_url or None)
    if spec.startswith("sidecar:"):
        rest = spec[len("sidecar:") :]
        try:
            label, base_url, model_id = rest.split("@", 2)
        except ValueError:
            sys.exit(f"HATA: sidecar tanımı 'sidecar:<etiket>@<base_url>@<model_id>' biçiminde olmalı: {spec!r}")
        return label, OllamaVisionExtractor(model=model_id, base_url=base_url)
    sys.exit(f"HATA: tanınmayan engine tanımı: {spec!r}")


def _build_chain(engine) -> FallbackDocumentExtractor:
    """The same chain get_document_extractor() builds, with `engine` swapped
    in for whichever OllamaVisionExtractor production would otherwise use --
    this is what "score the full production chain per engine" means."""
    if isinstance(engine, TesseractExtractor):
        return FallbackDocumentExtractor(
            extractors=[
                PlainTextExtractor(),
                OpenDataLoaderExtractor(),
                PdfiumExtractor(),
                engine,
            ],
            header_repair=None,
        )
    return FallbackDocumentExtractor(
        extractors=[
            PlainTextExtractor(),
            OpenDataLoaderExtractor(),
            PdfiumExtractor(),
            TesseractExtractor(),
            engine,
        ],
        header_repair=engine,
    )


def _score(expected: dict, got: dict) -> dict:
    found = raw_exact = norm_exact = 0
    for key, value in expected.items():
        candidate = got.get(key)
        if candidate:
            found += 1
        if str(candidate or "").strip() == str(value).strip():
            raw_exact += 1
        elif candidate and _normalise(candidate) == _normalise(value):
            norm_exact += 1
    return {"found": found, "raw_exact": raw_exact, "norm_exact": norm_exact}


async def _run_engine(name: str, engine, documents: list) -> dict:
    chain = _build_chain(engine)
    per_doc = {}
    totals = {"found": 0, "raw_exact": 0, "norm_exact": 0, "raw_found": 0, "raw_raw_exact": 0, "raw_norm_exact": 0}
    total_fields = sum(len(expected) for _, _, expected in documents)
    started_all = time.time()

    for doc_name, pdf_bytes, expected in documents:
        line = f"  {doc_name[:40]:42s}"
        doc_started = time.time()
        try:
            raw_result = await engine.extract(pdf_bytes, mime_type="application/pdf")
            raw_fields = parse_labelled_fields(raw_result.text)
        except Exception as exc:  # noqa: BLE001 - a failed engine recovers nothing
            print(f"{line} [RAW extract FAILED: {exc}]")
            raw_fields = {}
        raw_score = _score(expected, raw_fields)

        try:
            chain_result = await chain.extract(pdf_bytes, file_name=doc_name, mime_type="application/pdf")
            chain_fields = parse_labelled_fields(chain_result.text)
        except Exception as exc:  # noqa: BLE001
            print(f"{line} [CHAIN extract FAILED: {exc}]")
            chain_fields = {}
        chain_score = _score(expected, chain_fields)
        elapsed = time.time() - doc_started

        per_doc[doc_name] = {"raw": raw_score, "chain": chain_score, "seconds": elapsed}
        totals["found"] += chain_score["found"]
        totals["raw_exact"] += chain_score["raw_exact"]
        totals["norm_exact"] += chain_score["norm_exact"]
        totals["raw_found"] += raw_score["found"]
        totals["raw_raw_exact"] += raw_score["raw_exact"]
        totals["raw_norm_exact"] += raw_score["norm_exact"]

        print(
            f"{line} raw {raw_score['found']}/{len(expected)} "
            f"(tam {raw_score['raw_exact']}+yakın {raw_score['norm_exact']})  |  "
            f"zincir {chain_score['found']}/{len(expected)} "
            f"(tam {chain_score['raw_exact']}+yakın {chain_score['norm_exact']})  "
            f"{elapsed:.1f}s"
        )

    return {
        "per_doc": per_doc,
        "totals": totals,
        "total_fields": total_fields,
        "wall_clock": time.time() - started_all,
    }


def _print_summary(all_results: dict) -> None:
    total_fields = None
    print("\n" + "=" * 100)
    print(f"{'motor':30s} {'ham bulunan':>14s} {'zincir bulunan':>16s} {'zincir tam':>12s} {'zincir yakın':>13s} {'süre':>9s}")
    for name, result in all_results.items():
        t = result["totals"]
        total_fields = result["total_fields"]
        print(
            f"{name:30s} {t['raw_found']:6d}/{total_fields:<6d} "
            f"{t['found']:8d}/{total_fields:<6d} {t['raw_exact']:5d}/{total_fields:<5d} "
            f"{t['norm_exact']:6d}/{total_fields:<5d} {result['wall_clock']:8.1f}s"
        )
    print("-" * 100)
    print(
        "'ham bulunan': tek motorun (zincirsiz) tam sayfa çıktısından alan kurtarma. "
        "'zincir': tam üretim zinciri (Tesseract + bu motorun başlık onarımı). "
        "'tam': değer birebir kaynakla aynı. 'yakın': yalnızca boşluk/büyük-küçük harf farkı var "
        "(örn. el yazısı ek not aynı satırda kaldıysa) -- toplam kayıp değil, kısmi başarı."
    )


def _load_results_file(path: str) -> dict:
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def _save_results_file(path: str, results: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)


async def run(engine_specs: list[str], results_file: str, report_only: bool) -> None:
    all_results = _load_results_file(results_file)

    if not report_only:
        ground_truth = _load_ground_truth()
        documents = _load_documents(ground_truth)
        total_fields = sum(len(expected) for _, _, expected in documents)
        print("=" * 100)
        print(f"  Gerçek derlem OCR karşılaştırması — {len(documents)} belge, {total_fields} etiketli alan")
        print("=" * 100)

        for spec in engine_specs:
            name, engine = _parse_engine_spec(spec)
            print(f"\n--- {name} ---")
            all_results[name] = await _run_engine(name, engine, documents)
            _save_results_file(results_file, all_results)

    if all_results:
        _print_summary(all_results)
    else:
        print("Henüz sonuç yok -- en az bir --engine ile çalıştırın.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--engine", action="append", default=[], dest="engines")
    parser.add_argument("--results-file", default=DEFAULT_RESULTS_FILE)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Skip running anything; just print the table from --results-file.",
    )
    args = parser.parse_args()

    if not args.engines and not args.report_only:
        sys.exit("HATA: en az bir --engine belirtin (veya --report-only kullanın).")

    asyncio.run(run(args.engines, args.results_file, args.report_only))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
