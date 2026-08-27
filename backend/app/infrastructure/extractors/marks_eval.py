"""Shared scoring/corpus helpers for measuring `detect_marks` against real,
hand-labelled ground truth.

Split out of `scripts/evaluate_marks.py` so the same logic can also be
pinned as a real assertion in `tests/performance/test_marks_accuracy.py`
(`real_corpus` marker) -- a script printing a number nobody re-checks is
exactly how the original 0%-recall signature bug (see `marks.py`'s own
history) went unnoticed for a while. Both the script and the test import
from here rather than each keeping their own copy.

Requires `pypdfium2`, already in `requirements.txt` (not `-dev`), since the
production extraction chain uses it too (`PdfiumExtractor`).
"""

import json
from typing import Optional

from app.infrastructure.extractors.base import is_scanned_text_layer

try:
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover -- both callers fail fast without it
    pdfium = None

RENDER_DPI = 300


def load_ground_truth(path: str) -> dict:
    """Load a hand-labelled ground-truth JSON (see
    `datasets/resmi_yazisma/ocr_ground_truth.json`), dropping its `_meta` key."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data.pop("_meta", None)
    return data


def confusion(predicted: bool, actual: bool) -> str:
    """Classify one (predicted, actual) boolean pair as tp/fp/fn/tn."""
    if predicted and actual:
        return "tp"
    if predicted and not actual:
        return "fp"
    if not predicted and actual:
        return "fn"
    return "tn"


def precision_recall(counts: dict) -> tuple[float, float]:
    """Precision/recall from a `{"tp": n, "fp": n, "fn": n}`-shaped counter.
    Returns `nan` for either ratio if its denominator is zero."""
    tp, fp, fn = counts.get("tp", 0), counts.get("fp", 0), counts.get("fn", 0)
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    return precision, recall


def should_rasterise(pdf_bytes: bytes) -> bool:
    """Whether this document is one `detect_marks` should be scored against.

    True for a genuine scan (no real text layer) OR Class A (a scanner's own
    junk OCR text layer sitting over a full-page raster -- see
    `is_scanned_text_layer`'s own docstring). A cheap `>= 20 chars in the
    first 3 pages` text-layer check alone misses Class A, since it has a
    real (if junk) text layer -- `FallbackDocumentExtractor` still escalates
    such a document to OCR/vision repair on quality grounds
    (`scan_text_layer_probe`), so it's still a genuine scan target for
    `detect_marks` in production and must not be silently skipped here.
    """
    return _has_no_text_layer(pdf_bytes) or is_scanned_text_layer(pdf_bytes)


def _has_no_text_layer(pdf_bytes: bytes) -> bool:
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


def rasterise(pdf_bytes: bytes, *, pages: Optional[list[int]] = None) -> list:
    """Rasterise a PDF at `RENDER_DPI`, matching production's own render
    scale (see `BaseDocumentExtractor.extract`'s `raster_cache`).

    Args:
        pdf_bytes: Raw PDF bytes.
        pages: 0-based page indices to render; every page if omitted.

    Returns:
        Rendered pages as PIL images, in the given (or full) page order.
    """
    scale = RENDER_DPI / 72
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        indices = pages if pages is not None else range(len(document))
        return [document[i].render(scale=scale).to_pil() for i in indices]
    finally:
        document.close()
