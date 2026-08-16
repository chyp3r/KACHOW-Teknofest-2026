"""Measure signature/stamp/handwriting detection against the real scanned corpus.

Originally counts-only: there was no hand-labelled ground truth for
signatures or stamps on this project's document corpus (unlike
`evaluate_ocr_fields.py`, which has a clean-text reference to compare
against), so precision and recall could not be honestly claimed. That has
since changed -- `datasets/resmi_yazisma/ocr_ground_truth.json` hand-labels
`has_signature`/`has_stamp` (page 1 only) for 15 real documents, as a
by-product of an OCR-model comparison that required visually reading each
page anyway. Pass `--ground-truth` to score against it; omit it and this
still runs exactly as before (counts only, over however many documents you
point it at).

    python scripts/evaluate_marks.py
    python scripts/evaluate_marks.py --limit 10
    python scripts/evaluate_marks.py --corpus datasets/resmi_yazisma/00_gelen_kaynaklar/cevap_yazisi --verbose
    python scripts/evaluate_marks.py --ground-truth datasets/resmi_yazisma/ocr_ground_truth.json

The default corpus is this project's own real scanned ministry replies --
the same 45 image-only `CY-*.pdf` under
`datasets/resmi_yazisma/00_gelen_kaynaklar/cevap_yazisi/` that
`HEADER_BAND_FRACTION`, the four `field_parser.py` fixes, and this module's
own `_MAX_STROKE_RUN_DENSITY` were all calibrated against.
"""

import argparse
import glob
import json
import os
import sys
import time
from collections import Counter

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.infrastructure.extractors.marks import detect_marks  # noqa: E402

try:
    import pypdfium2 as pdfium
except ImportError:
    sys.exit("HATA: 'pypdfium2' gerekli. Kurulum: pip install -r backend/requirements-dev.txt")

DEFAULT_CORPUS = os.path.join(
    os.path.dirname(__file__), "..", "datasets", "resmi_yazisma",
    "00_gelen_kaynaklar", "cevap_yazisi",
)
RENDER_DPI = 300


def _load_ground_truth(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data.pop("_meta", None)
    return data


def _confusion(predicted: bool, actual: bool) -> str:
    if predicted and actual:
        return "tp"
    if predicted and not actual:
        return "fp"
    if not predicted and actual:
        return "fn"
    return "tn"


def _precision_recall(counts: dict) -> tuple[float, float]:
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    return precision, recall


def rasterise(pdf_bytes: bytes) -> list:
    """Rasterise every page of a PDF at RENDER_DPI -- every page, not just
    the first, matching production (see BaseDocumentExtractor.extract's own
    raster_cache, shared across every page of a document)."""
    scale = RENDER_DPI / 72
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        return [page.render(scale=scale).to_pil() for page in document]
    finally:
        document.close()


def _has_no_text_layer(pdf_bytes: bytes) -> bool:
    """Cheap filter: only genuine scans exercise the OCR path detect_marks
    targets. A born-digital PDF is never rasterised in production at all
    (see PdfiumExtractor/OpenDataLoaderExtractor's own `supports()`), so
    running detection against one here would measure something production
    never does."""
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        for index, page in enumerate(document):
            if index >= 3:
                break
            text_page = page.get_textpage()
            try:
                if len(text_page.get_text_range().strip()) >= 20:
                    return False
            finally:
                text_page.close()
        return True
    finally:
        document.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", default=DEFAULT_CORPUS, help="PDF içeren klasör.")
    parser.add_argument("--limit", type=int, default=None, help="En fazla kaç belge işlensin.")
    parser.add_argument(
        "--verbose", action="store_true",
        help="Her belge için bulunan her bölgeyi (tür, sayfa, bbox, güven) tek tek yazdır.",
    )
    parser.add_argument(
        "--ground-truth", default=None,
        help=(
            "İmza/mühür etiketli JSON dosyası (bkz. "
            "datasets/resmi_yazisma/ocr_ground_truth.json). Verilirse yalnızca "
            "sayım değil, bu dosyada bulunan belgeler için 1. sayfa üzerinden "
            "kesinlik/duyarlılık (precision/recall) de raporlanır."
        ),
    )
    args = parser.parse_args()

    paths = sorted(glob.glob(os.path.join(args.corpus, "*.pdf")))
    if args.limit:
        paths = paths[: args.limit]
    if not paths:
        sys.exit(f"HATA: '{args.corpus}' içinde .pdf bulunamadı.")

    ground_truth = _load_ground_truth(args.ground_truth) if args.ground_truth else {}
    # tp/fp/fn/tn counts per kind, page 1 only -- ground truth was labelled
    # from page 1 alone, so scoring later pages against it would be scoring
    # against nothing and silently inflate false negatives.
    confusion = {"signature": Counter(), "stamp": Counter()}

    kind_totals = Counter()
    docs_with_any_mark = 0
    docs_scanned = 0
    started = time.time()

    print(f"{'belge':40} {'sayfa':>5} {'imza':>5} {'mühür':>6} {'el yazısı':>9} {'süre':>7}")
    print("-" * 78)

    for path in paths:
        name = os.path.basename(path)
        with open(path, "rb") as handle:
            pdf_bytes = handle.read()

        if not _has_no_text_layer(pdf_bytes):
            continue  # not a scan -- production never rasterises this either
        docs_scanned += 1

        doc_started = time.time()
        pages = rasterise(pdf_bytes)
        doc_marks = []
        for page_number, page_image in enumerate(pages, start=1):
            doc_marks.extend(detect_marks(page_image, page_number))
        elapsed = time.time() - doc_started

        counts = Counter(mark.kind for mark in doc_marks)
        if doc_marks:
            docs_with_any_mark += 1
        kind_totals.update(counts)

        gt_marker = ""
        if name in ground_truth:
            page_1_kinds = {mark.kind for mark in doc_marks if mark.page == 1}
            for kind in ("signature", "stamp"):
                predicted = kind in page_1_kinds
                actual = bool(ground_truth[name].get(f"has_{kind}"))
                confusion[kind][_confusion(predicted, actual)] += 1
            gt_marker = "  [etiketli]"

        print(
            f"{name[:40]:40} {len(pages):>5} {counts['signature']:>5} "
            f"{counts['stamp']:>6} {counts['handwriting']:>9} {elapsed:>6.1f}s{gt_marker}"
        )
        if args.verbose:
            for mark in doc_marks:
                print(f"    {mark.kind:12} sayfa={mark.page} bbox={mark.bbox} güven={mark.confidence}")

    total_elapsed = time.time() - started
    print("-" * 78)
    print(
        f"{docs_scanned} taranmış belge (metin katmanlı belgeler atlandı), "
        f"{docs_with_any_mark} belgede en az bir bölge bulundu, {total_elapsed:.1f}s"
    )
    print(f"toplam: {dict(kind_totals)}")
    print()

    if ground_truth:
        labelled = sum(1 for name in ground_truth if os.path.basename(name) in {os.path.basename(p) for p in paths})
        print(f"=== Kesinlik/duyarlılık -- {labelled} etiketli belge, yalnızca 1. sayfa ===")
        print(f"{'tür':12} {'kesinlik':>10} {'duyarlılık':>12} {'tp':>4} {'fp':>4} {'fn':>4} {'tn':>4}")
        for kind in ("signature", "stamp"):
            counts = confusion[kind]
            precision, recall = _precision_recall(counts)
            print(
                f"{kind:12} {precision:>10.2f} {recall:>12.2f} "
                f"{counts['tp']:>4} {counts['fp']:>4} {counts['fn']:>4} {counts['tn']:>4}"
            )
        print()
        print(
            "'kesinlik' (precision): detect_marks bu türü bulduğunda gerçekten "
            "orada mı. 'duyarlılık' (recall): gerçekte bu tür varken detect_marks "
            "onu buluyor mu. Ground truth'un 'has_stamp' tanımı yalnızca gerçek "
            "uygulanmış bir mühür/kaşe içindir -- antetteki T.C./bakanlık amblemi "
            "sayılmaz (bkz. ocr_ground_truth.json'un _meta.mark_labels alanı); "
            "marks.py'nin mühür sınıflandırması bu ayrımı yapmadığından, mühür "
            "kesinliğinin düşük çıkması beklenen ve dürüst bir sonuçtur, hata değil."
        )
    else:
        print(
            "Not: bu sayılar doğruluk iddiası değildir -- --ground-truth "
            "verilmedi (bkz. bu betiğin ve marks.py'nin modül docstring'i). "
            "Eşikleri ayarlarken --verbose ile gerçek belgeleri gözden geçirin."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
