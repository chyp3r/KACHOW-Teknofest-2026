"""Measure OCR field recovery on the REAL scanned corpus, not synthetic evrak.

Sibling to `evaluate_ocr_fields.py`, which stays as the fast, reproducible
synthetic-corpus benchmark (12 degraded documents, 62 labelled fields) that
already decided deepseek-ocr as the shipped default. This script exists for a
different question: does a candidate model actually help on the real,
handwriting-and-letterhead-carrying documents this project was built to
handle, not a synthetically degraded stand-in for them.

Ground truth: `datasets/resmi_yazisma/ocr_ground_truth.json`, 23 hand-labelled
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

Scored fields are split into two groups, and reported apart, never blended
into one number: the HEADER block (sayi/tarih/konu/muhatap/gonderen_kurum)
and the SIGNATURE block (imza_sahibi/imza_unvani). The split is the whole
point of the comparison. `header_repair` re-transcribes the top
HEADER_BAND_FRACTION of every scanned page for every engine, so header
recovery converges and a blended total reads as "all vision models are
interchangeable". The signature block sits well below that band, and is
where engines genuinely diverge -- measured on this corpus, a wet signature
over the printed name leaves OpenDataLoader/Tesseract with a mangled
"İF; BOZDAG ;" (or no line at all) where a full-page vision pass recovers
"Bekir BOZDAĞ". Before this split existed the script scored HEADER_FIELD
alone and was structurally blind to exactly the difference it was being
used to measure.

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

from app.ai.compliance import (  # noqa: E402
    HEADER_FIELD,
    count_header_fields,
    has_signature,
    parse_labelled_fields,
)
from app.infrastructure.extractors import (  # noqa: E402
    FallbackDocumentExtractor,
    OllamaVisionExtractor,
    OpenDataLoaderExtractor,
    PdfiumExtractor,
    PlainTextExtractor,
    TesseractExtractor,
)
from app.infrastructure.extractors.base import is_scanned_text_layer  # noqa: E402

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
#: The same tuple `get_document_extractor()`'s `header_field_probe` is scored
#: against in production -- imported, not redeclared, so this benchmark can
#: never silently drift from what the extraction-acceptance gate actually
#: checks.
HEADER_KEYS = HEADER_FIELD
#: Scored separately from the header block, and the reason this benchmark
#: was extended at all: the header band is exactly where `header_repair`
#: already levels every engine, so scoring it alone makes distinct vision
#: models look interchangeable. The signature block is where they actually
#: diverge -- measured on this same corpus, a wet signature over the printed
#: name destroys it for OpenDataLoader/Tesseract ("İF; BOZDAG ;" for "Bekir
#: BOZDAĞ", or the line missing entirely) while a full-page vision pass
#: recovers it. Folding the two groups into one total would re-hide exactly
#: the difference this measurement exists to show, so `_score` counts them
#: apart and `_print_summary` reports them apart.
SIGNATURE_KEYS = ("imza_sahibi", "imza_unvani")
FIELD_KEYS = (*HEADER_KEYS, *SIGNATURE_KEYS)
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
    this is what "score the full production chain per engine" means.

    Also wires the same `header_field_probe`/`scan_text_layer_probe`
    production passes. Omitting these was a real, previously-shipped bug in
    this exact function: `FallbackDocumentExtractor` is built by hand here
    rather than via `get_document_extractor()`, so a wiring change made only
    in production silently never reaches this benchmark -- the chain still
    constructs, still runs, and still prints a confident-looking comparison
    table, just scoring the OLD acceptance behaviour under a NEW model's
    name. There is no test that catches this class of bug; only wiring it
    identically to production does.
    """
    if isinstance(engine, TesseractExtractor):
        return FallbackDocumentExtractor(
            extractors=[
                PlainTextExtractor(),
                OpenDataLoaderExtractor(),
                PdfiumExtractor(),
                engine,
            ],
            header_repair=None,
            header_field_probe=count_header_fields,
            scan_text_layer_probe=is_scanned_text_layer,
            signature_probe=has_signature,
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
        header_field_probe=count_header_fields,
        scan_text_layer_probe=is_scanned_text_layer,
        signature_probe=has_signature,
    )


def _score(expected: dict, got: dict) -> dict:
    """Count recovery, split into the header block and the signature block.

    The split is the point: `header_repair` already re-transcribes the top
    `HEADER_BAND_FRACTION` of every scanned page, so header-field recovery
    converges across engines and a combined total would read as "every model
    is the same". The signature block sits well below that band and is where
    engines genuinely differ. Totals are still reported, but never on their
    own.
    """
    counters = {
        group: {"found": 0, "raw_exact": 0, "norm_exact": 0, "expected": 0}
        for group in ("header", "signature")
    }
    for key, value in expected.items():
        group = "signature" if key in SIGNATURE_KEYS else "header"
        bucket = counters[group]
        bucket["expected"] += 1
        candidate = got.get(key)
        if candidate:
            bucket["found"] += 1
        if str(candidate or "").strip() == str(value).strip():
            bucket["raw_exact"] += 1
        elif candidate and _normalise(candidate) == _normalise(value):
            bucket["norm_exact"] += 1

    total = {
        metric: counters["header"][metric] + counters["signature"][metric]
        for metric in ("found", "raw_exact", "norm_exact", "expected")
    }
    return {**total, "header": counters["header"], "signature": counters["signature"]}


async def _run_engine(name: str, engine, documents: list) -> dict:
    chain = _build_chain(engine)
    per_doc = {}
    # "chain"/"raw" are the two passes; each carries the header/signature
    # split `_score` produces, so the summary can report them apart.
    totals = {
        pass_name: {
            group: {"found": 0, "raw_exact": 0, "norm_exact": 0, "expected": 0}
            for group in ("header", "signature")
        }
        for pass_name in ("chain", "raw")
    }
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
        for pass_name, score in (("chain", chain_score), ("raw", raw_score)):
            for group in ("header", "signature"):
                for metric in ("found", "raw_exact", "norm_exact", "expected"):
                    totals[pass_name][group][metric] += score[group][metric]

        def _cell(score: dict) -> str:
            h, s = score["header"], score["signature"]
            return (
                f"bşl {h['found']}/{h['expected']}(t{h['raw_exact']}) "
                f"imz {s['found']}/{s['expected']}(t{s['raw_exact']})"
            )

        print(f"{line} ham {_cell(raw_score)}  |  zincir {_cell(chain_score)}  {elapsed:.1f}s")

    return {
        "per_doc": per_doc,
        "totals": totals,
        "total_fields": total_fields,
        "wall_clock": time.time() - started_all,
    }


def _print_summary(all_results: dict) -> None:
    """Print the engine comparison, header and signature blocks apart.

    Reported separately on purpose -- see `_score`. A single blended total
    would let the header block (which `header_repair` already equalises
    across engines) mask the signature block, which is the column that
    actually separates one vision model from another.
    """
    print("\n" + "=" * 108)
    print(
        f"{'motor':28s} | {'ZİNCİR (üretim yolu)':^37s} | {'HAM (tek motor)':^25s} | {'süre':>8s}"
    )
    print(
        f"{'':28s} | {'başlık bul':>11s} {'imza bul':>10s} {'imza tam':>13s} | "
        f"{'başlık bul':>11s} {'imza bul':>12s} | {'':>8s}"
    )
    print("-" * 108)

    for name, result in all_results.items():
        t = result["totals"]
        # Back-compat: a results file written before the header/signature
        # split has flat totals and no per-group keys. Skipped loudly
        # rather than crashing or silently printing zeros -- a stale row
        # next to fresh ones would be the most misleading output possible.
        if "chain" not in t:
            print(f"{name:28s} | (eski biçim sonuç -- bu motoru yeniden koşun)")
            continue
        ch, rw = t["chain"], t["raw"]
        print(
            f"{name:28s} | "
            f"{ch['header']['found']:5d}/{ch['header']['expected']:<5d} "
            f"{ch['signature']['found']:4d}/{ch['signature']['expected']:<5d} "
            f"{ch['signature']['raw_exact']:6d}/{ch['signature']['expected']:<6d} | "
            f"{rw['header']['found']:5d}/{rw['header']['expected']:<5d} "
            f"{rw['signature']['found']:5d}/{rw['signature']['expected']:<6d} | "
            f"{result['wall_clock']:7.1f}s"
        )

    print("-" * 108)
    print(
        "ZİNCİR = tam üretim yolu (Tesseract + bu motorun başlık onarımı + imza\n"
        "  okunamazsa tam-sayfa yükseltmesi) -- üretimde gerçekten olan şey.\n"
        "HAM = motorun tek başına, zincirsiz, tüm sayfaları okuması -- motorun\n"
        "  kendi tavan performansı; süreyi domine eden de budur.\n"
        "'imza tam' sütunu belirleyici olan: başlık bölgesinde header_repair zaten\n"
        "  her motoru eşitliyor, motorlar asıl imza bloğunda ayrışıyor."
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
