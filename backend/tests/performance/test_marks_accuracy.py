"""Pins `detect_marks`'s real-world signature-detection accuracy.

`tests/unit/infrastructure/test_marks.py` only checks the heuristics against
synthetic, unambiguous shapes -- explicitly not an accuracy claim (see its
own docstring). This is the accuracy claim: it rasterises page 1 of every
document `datasets/resmi_yazisma/ocr_ground_truth.json` hand-labels and
scores `detect_marks`'s signature output against the label.

Exists so a future change to `marks.py`'s thresholds can't silently regress
real-world accuracy again unnoticed -- exactly what happened to the original
signature detector: an early ground-truth run found 0% recall, it got fixed,
and then nobody re-measured for a while (see `marks.py`'s own history, and
`_MAX_STROKE_RUN_DENSITY`'s docstring for the most recent round of this).

Opt-in (`real_corpus` marker, `make test-corpus`) rather than part of the
default lane: real PDF rasterisation via `pypdfium2` against ~20 documents is
genuinely slow relative to the rest of this suite, same reasoning as the
`performance`/`e2e` markers (see `pyproject.toml`'s own comments on each).

The floors below are the measured values as of the `_MAX_STROKE_RUN_DENSITY`
fix (scripts/evaluate_marks.py --ground-truth
datasets/resmi_yazisma/ocr_ground_truth.json): precision 1.00 (0 false
positives), recall 0.94 (15/16 -- one remaining miss, CY-002, whose real
signature only detects on page 2; see that constant's own docstring for why
this was accepted rather than chased further, since fixing it introduced a
new false positive on CY-005 instead of removing this one).
"""

import glob
import os

import pytest

from app.infrastructure.extractors.marks import detect_marks
from app.infrastructure.extractors.marks_eval import (
    confusion,
    load_ground_truth,
    precision_recall,
    rasterise,
    should_rasterise,
)

pytestmark = pytest.mark.real_corpus

# `datasets/` isn't inside `backend/` on the host -- it's bind-mounted
# directly at `/workspace/datasets` in the backend container (see
# `compose.yml`'s `./datasets:/workspace/datasets`), i.e. two levels up from
# this file's own directory (`tests/performance/`), not three. This test
# only ever runs there (`docker compose run --rm backend pytest ...`, same
# as every other test in this suite).
_WORKSPACE_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_CORPUS_DIR = os.path.join(_WORKSPACE_ROOT, "datasets", "resmi_yazisma", "00_gelen_kaynaklar", "cevap_yazisi")
_GROUND_TRUTH_PATH = os.path.join(_WORKSPACE_ROOT, "datasets", "resmi_yazisma", "ocr_ground_truth.json")

#: Measured floors -- see module docstring. The recall floor is the exact
#: 15/16 fraction, not the script's rounded-to-2-decimals 0.94 display value
#: (0.9375 < 0.94, so using the rounded figure here would fail on the very
#: commit that measured it). A future run must not score below these; if
#: `marks.py` genuinely improves further, raise both floors to match (never
#: lower them without a documented reason, same rule as `--cov-fail-under`
#: in the Makefile's own `test` target comment).
_MIN_SIGNATURE_PRECISION = 1.00
_MIN_SIGNATURE_RECALL = 15 / 16


def test_signature_detection_precision_and_recall_on_the_real_ground_truth_corpus():
    ground_truth = load_ground_truth(_GROUND_TRUTH_PATH)
    counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    scored = 0

    for name, labels in ground_truth.items():
        path = os.path.join(_CORPUS_DIR, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as handle:
            pdf_bytes = handle.read()
        if not should_rasterise(pdf_bytes):
            continue

        (page_one,) = rasterise(pdf_bytes, pages=[0])
        marks = detect_marks(page_one, page=1)
        predicted = any(mark.kind == "signature" for mark in marks)
        actual = bool(labels.get("has_signature"))
        counts[confusion(predicted, actual)] += 1
        scored += 1

    assert scored == 23, (
        f"Expected to score all 23 hand-labelled documents, only scored {scored} -- "
        "a document went missing from the corpus dir or started failing should_rasterise."
    )

    precision, recall = precision_recall(counts)
    assert precision >= _MIN_SIGNATURE_PRECISION, (
        f"Signature precision regressed: {precision:.2f} < {_MIN_SIGNATURE_PRECISION} "
        f"(tp={counts['tp']} fp={counts['fp']} fn={counts['fn']} tn={counts['tn']})"
    )
    assert recall >= _MIN_SIGNATURE_RECALL, (
        f"Signature recall regressed: {recall:.2f} < {_MIN_SIGNATURE_RECALL} "
        f"(tp={counts['tp']} fp={counts['fp']} fn={counts['fn']} tn={counts['tn']})"
    )


def test_ground_truth_corpus_files_all_exist():
    """Guards the test above's own premise -- if a labelled filename drifts
    out of sync with the corpus directory, the accuracy test's `scored == 23`
    assertion would catch it too, but this pinpoints which file specifically."""
    ground_truth = load_ground_truth(_GROUND_TRUTH_PATH)
    corpus_files = {os.path.basename(p) for p in glob.glob(os.path.join(_CORPUS_DIR, "*.pdf"))}
    missing = set(ground_truth) - corpus_files
    assert not missing, f"Ground truth references file(s) not present in the corpus dir: {missing}"
