"""Unit tests for signature/stamp/handwriting mark detection.

Two levels, deliberately kept separate:
  - `_classify` tested directly against hand-built numpy ink masks, for
    precise control over the shape features being tested (stroke width,
    baseline, aspect ratio, density) without depending on connected-
    component detection also being correct.
  - `detect_marks` tested end-to-end against small synthetic PIL pages
    (real Pillow + real numpy, nothing mocked -- geometry and pixel math
    must be genuine), covering the whole pipeline including the width-
    fraction filter that `_classify` alone never sees.

No accuracy claim is being tested here (there is no ground truth -- see the
module docstring in app.infrastructure.extractors.marks): these confirm the
heuristics behave as documented on unambiguous synthetic cases, not that
they achieve any particular precision on real scans.
"""

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.infrastructure.extractors.marks import (
    DetectedMark,
    _baseline_std,
    _classify,
    _stroke_run_density,
    _stroke_width_cv,
    detect_marks,
)


# ==========================================
# _classify -- shape heuristics in isolation
# ==========================================
def test_a_textured_ring_shaped_block_is_classified_as_a_stamp():
    """A real seal is fine detailed artwork -- a ring of text, a border, an
    emblem -- not a flat solid fill (see test_a_solid_fill_is_not_a_stamp
    just below for why that matters: a solid fill is actually the wrong
    synthetic stand-in for a stamp)."""
    region = _textured_ring()
    kind, confidence = _classify(region, y_center_fraction=0.5)
    assert kind == "stamp"
    assert 0.0 < confidence <= 1.0


def test_a_solid_fill_is_not_a_stamp():
    """Regression, found via real ground-truth labelling (see
    _STAMP_MIN_RUN_DENSITY's own comment in marks.py): a flat solid fill has
    exactly one continuous ink run per row -- the same low run-density shape
    a genuine signature has, not what a real seal's detailed artwork looks
    like. A real Turkish resmi mühür has internal structure (a text ring, a
    border, an emblem) and was measured on the real corpus at run density
    2.18-9.28 -- nothing like a flat 200x200 fill's 0.5. This is why the
    canonical 'stamp' fixture above is a textured ring, not a solid block."""
    region = np.ones((200, 200), dtype=bool)
    kind, _ = _classify(region, y_center_fraction=0.5)
    assert kind != "stamp"


def test_a_small_solid_square_is_not_a_stamp():
    """Regression: without a minimum size, a small dense square -- a printed
    character, a logo fragment, a bullet point -- passes the exact same
    aspect-ratio/density test a genuine seal does. Measured on the real
    scanned corpus this module targets: several sub-150px 'stamps' turned
    out to be exactly this (see scripts/evaluate_marks.py)."""
    region = np.ones((80, 80), dtype=bool)  # same shape as above, just smaller
    kind, _ = _classify(region, y_center_fraction=0.5)
    assert kind is None


def test_a_wide_thin_uniform_band_is_not_a_mark():
    """Simulates a line of printed text: several evenly-spaced, identically
    sized ink blocks on a shared baseline -- low stroke-width variance, low
    baseline variance, not compact enough to be a stamp."""
    region = np.zeros((30, 300), dtype=bool)
    for x in range(10, 290, 20):
        region[10:20, x : x + 4] = True  # uniform 4px-wide "glyphs", same y-range
    kind, confidence = _classify(region, y_center_fraction=0.5)
    assert kind is None
    assert confidence == 0.0


def test_an_irregular_blob_in_the_bottom_third_is_a_signature():
    region = _irregular_scribble()
    kind, confidence = _classify(region, y_center_fraction=0.85)
    assert kind == "signature"
    assert 0.0 < confidence <= 1.0


def test_the_same_irregular_blob_elsewhere_is_handwriting_not_a_signature():
    """The classifier's only positional signal: identical ink shape, only
    the page position differs, per RYUEHY m.17 placing signatures at the
    bottom of a document."""
    region = _irregular_scribble()
    kind, _ = _classify(region, y_center_fraction=0.2)
    assert kind == "handwriting"


def test_a_compact_signature_is_not_intercepted_by_the_stamp_check():
    """Regression, found via real ground-truth labelling: CY-012's actual
    wet signature over 'Yaşar GÜLER' measured aspect ratio 1.69, ink density
    0.121, and 320x540px -- comfortably inside every stamp-shape threshold
    (_STAMP_ASPECT_RATIO_RANGE, _STAMP_MIN_INK_DENSITY,
    _STAMP_MIN_DIMENSION_PX), so before _STAMP_MIN_RUN_DENSITY was added the
    stamp check matched it first and this module reported
    is_signed=False, has_stamp=True for a document that is, in fact, signed
    -- measured system-wide as 0% signature recall across 15 hand-labelled
    real documents (see scripts/evaluate_marks.py --ground-truth). This
    synthetic region is built to reproduce exactly that shape: large and
    dense enough to pass every stamp gate except run density, which a few
    thick continuous pen strokes keep low."""
    region = _compact_signature()
    aspect_ratio = region.shape[1] / region.shape[0]
    assert 0.55 <= aspect_ratio <= 1.8, "fixture must actually satisfy the stamp aspect-ratio range"
    assert min(region.shape) >= 150, "fixture must actually satisfy the stamp size floor"

    kind, _ = _classify(region, y_center_fraction=0.8)

    assert kind == "signature"


def test_a_signature_with_a_below_average_baseline_std_still_qualifies():
    """Regression: real signatures measured on the corpus (CY-012, CY-009,
    CY-006 -- see _HANDWRITING_MIN_BASELINE_STD's own comment in marks.py)
    had baseline_std 0.119-0.139, below the original 0.15 floor calibrated
    against general handwritten annotations rather than signatures
    specifically. A name written along a rough line has less baseline
    variance than a scattered margin note."""
    region = _compact_signature()
    baseline_std = _baseline_std(region)
    assert 0.10 <= baseline_std < 0.15, (
        "fixture should sit in the exact gap the original threshold missed"
    )

    kind, _ = _classify(region, y_center_fraction=0.8)

    assert kind == "signature"


def test_an_empty_region_is_not_a_mark():
    region = np.zeros((50, 50), dtype=bool)
    kind, confidence = _classify(region, y_center_fraction=0.5)
    assert kind is None
    assert confidence == 0.0


def test_a_zero_dimension_region_does_not_raise():
    region = np.zeros((0, 50), dtype=bool)
    kind, confidence = _classify(region, y_center_fraction=0.5)
    assert kind is None
    assert confidence == 0.0


def _irregular_scribble() -> np.ndarray:
    """A hand-built ink mask with deliberately varying stroke width and an
    irregular top-of-ink baseline -- the shape `_classify` should read as
    handwritten, wherever it's positioned on the page."""
    region = np.zeros((60, 100), dtype=bool)
    # Runs of visibly different lengths on different rows, at different
    # vertical offsets -- high stroke-width CV, high baseline std.
    region[5:8, 10:15] = True     # thin, high on the page
    region[20:30, 25:45] = True   # thick, mid
    region[10:13, 50:52] = True   # thin, high
    region[35:45, 60:90] = True   # thick, low
    region[15:18, 70:75] = True   # thin, mid-high
    return region


def _compact_signature() -> np.ndarray:
    """A few thick, continuous, differently-angled pen strokes sized and
    shaped to reproduce the exact real failure this module's calibration
    found (see test_a_compact_signature_is_not_intercepted_by_the_stamp_check
    and test_a_signature_with_a_below_average_baseline_std_still_qualifies):
    large and dense enough to satisfy every stamp-shape threshold except run
    density, and with a baseline_std of ~0.13, in the gap between the
    original and lowered `_HANDWRITING_MIN_BASELINE_STD`. Unlike
    `_irregular_scribble` (deliberately small and sparse, to stay unambiguous
    for the basic shape tests), this is sized to actually collide with the
    stamp-shape thresholds on purpose."""
    img = Image.new("L", (220, 180), color=255)
    draw = ImageDraw.Draw(img)
    draw.line([(10, 150), (95, 60)], fill=0, width=22)
    draw.line([(70, 130), (205, 55)], fill=0, width=6)
    draw.line([(25, 70), (165, 160)], fill=0, width=11)
    draw.line([(150, 50), (195, 95)], fill=0, width=3)
    return np.asarray(img.convert("L")) < 128


def _textured_ring() -> np.ndarray:
    """A ring border plus internal radial hatching -- the fine detailed
    artwork a real seal (a text ring, a border, an emblem) actually looks
    like, as opposed to a flat solid fill (see test_a_solid_fill_is_not_a_stamp
    for why a solid fill is the wrong stand-in)."""
    img = Image.new("L", (200, 200), color=255)
    draw = ImageDraw.Draw(img)
    draw.ellipse([10, 10, 190, 190], outline=0, width=10)
    draw.ellipse([40, 40, 160, 160], outline=0, width=6)
    for x in range(0, 200, 14):
        draw.line([(x, 70), (x, 130)], fill=0, width=4)
    return np.asarray(img.convert("L")) < 128


# ==========================================
# _stroke_width_cv / _baseline_std -- the two feature functions directly
# ==========================================
def test_stroke_width_cv_is_zero_for_uniform_runs():
    region = np.zeros((10, 40), dtype=bool)
    region[2:5, 0:4] = True
    region[2:5, 10:14] = True
    region[2:5, 20:24] = True
    assert _stroke_width_cv(region) == 0.0


def test_stroke_width_cv_is_positive_for_varying_runs():
    region = np.zeros((10, 40), dtype=bool)
    region[2:5, 0:2] = True   # short run
    region[2:5, 10:30] = True  # long run
    assert _stroke_width_cv(region) > 0.0


def test_baseline_std_is_zero_for_columns_sharing_a_top_row():
    region = np.zeros((20, 10), dtype=bool)
    region[5:15, :] = True  # every column's top-of-ink is row 5
    assert _baseline_std(region) == 0.0


def test_baseline_std_is_positive_for_an_irregular_top_edge():
    region = np.zeros((20, 10), dtype=bool)
    region[2:15, 0:5] = True
    region[12:15, 5:10] = True
    assert _baseline_std(region) > 0.0


def test_stroke_run_density_is_low_for_a_few_continuous_strokes():
    """The feature that actually separates a short printed phrase from a
    handwritten mark (see the module's own comment on why stroke-width CV
    and baseline std alone do not, at word scale) -- a signature-shaped
    region has few runs relative to its width."""
    assert _stroke_run_density(_irregular_scribble()) < 1.5


def test_stroke_run_density_is_high_for_many_discrete_glyphs():
    """A row of separated small blocks, the shape a short printed phrase's
    individual letters make, has many runs relative to its width."""
    region = np.zeros((20, 200), dtype=bool)
    for x in range(0, 200, 10):
        region[5:15, x : x + 4] = True
    assert _stroke_run_density(region) > 1.5


# ==========================================
# detect_marks -- the full pipeline against synthetic pages
# ==========================================
def _blank_page(width=800, height=1000) -> Image.Image:
    return Image.new("L", (width, height), color=255)


def _draw_stamp_shaped_block(draw: ImageDraw.ImageDraw, bbox: tuple[int, int, int, int]) -> None:
    """Draw a textured ring -- not a solid fill, see
    test_a_solid_fill_is_not_a_stamp for why -- into `bbox` on a page."""
    x0, y0, x1, y1 = bbox
    draw.ellipse([x0, y0, x1, y1], outline=0, width=10)
    inset = (x1 - x0) // 5
    draw.ellipse([x0 + inset, y0 + inset, x1 - inset, y1 - inset], outline=0, width=6)
    for x in range(x0, x1, 14):
        draw.line([(x, (y0 + y1) // 2 - 30), (x, (y0 + y1) // 2 + 30)], fill=0, width=4)


def test_detect_marks_finds_a_stamp_shaped_block():
    page = _blank_page()
    draw = ImageDraw.Draw(page)
    _draw_stamp_shaped_block(draw, [550, 750, 750, 950])  # 200x200, above _STAMP_MIN_DIMENSION_PX

    marks = detect_marks(page, page=1)

    assert any(m.kind == "stamp" and m.page == 1 for m in marks)


def test_detect_marks_finds_a_signature_in_the_lower_page():
    page = _blank_page()
    draw = ImageDraw.Draw(page)
    # Several differently-angled, differently-widthed strokes near the
    # bottom of the page, the shape a real signature block has.
    draw.line([(100, 920), (160, 960)], fill=0, width=2)
    draw.line([(140, 900), (220, 950)], fill=0, width=8)
    draw.line([(200, 940), (260, 905)], fill=0, width=4)
    draw.line([(90, 955), (250, 910)], fill=0, width=10)

    marks = detect_marks(page, page=1)

    assert any(m.kind == "signature" for m in marks)


def test_detect_marks_ignores_a_full_width_text_line():
    """A row of uniform small blocks spanning most of the page width must
    not be reported at all -- neither as a mark (fails the shape checks)
    nor even reach classification (the width filter rejects it first)."""
    page = _blank_page()
    draw = ImageDraw.Draw(page)
    for x in range(20, 780, 15):
        draw.rectangle([x, 100, x + 5, 130], fill=0)

    marks = detect_marks(page, page=1)

    assert marks == []


def test_detect_marks_reports_nothing_on_a_blank_page():
    assert detect_marks(_blank_page(), page=1) == []


def test_detect_marks_never_raises_on_a_malformed_input():
    """Best-effort by contract: a detector bug must never fail a document
    upload. `None` is not a valid image and must degrade to no marks, not
    propagate an exception."""
    assert detect_marks(None, page=1) == []


def test_detect_marks_records_the_given_page_number():
    page = _blank_page()
    draw = ImageDraw.Draw(page)
    _draw_stamp_shaped_block(draw, [550, 750, 750, 950])  # 200x200, above _STAMP_MIN_DIMENSION_PX

    marks = detect_marks(page, page=3)

    assert marks and all(m.page == 3 for m in marks)


def test_bbox_is_normalised_to_the_0_1000_scale_independent_of_page_size():
    page = _blank_page(width=800, height=1000)
    draw = ImageDraw.Draw(page)
    _draw_stamp_shaped_block(draw, [550, 750, 750, 950])  # 200x200, above _STAMP_MIN_DIMENSION_PX

    marks = detect_marks(page, page=1)

    assert marks
    x0, y0, x1, y1 = marks[0].bbox
    assert 0 <= x0 < x1 <= 1000
    assert 0 <= y0 < y1 <= 1000


def test_detected_mark_is_a_real_pydantic_model():
    """Sanity check on the return type, since every field on it crosses into
    the analysis response schema (see SignatureAssessmentSchema)."""
    mark = DetectedMark(kind="stamp", page=1, bbox=(0, 0, 100, 100), confidence=0.8)
    assert mark.model_dump()["kind"] == "stamp"


@pytest.mark.parametrize("missing", ["np", "_PILImage"])
def test_detect_marks_degrades_when_a_dependency_is_missing(monkeypatch, missing):
    import app.infrastructure.extractors.marks as marks_module

    monkeypatch.setattr(marks_module, missing, None)
    assert detect_marks(_blank_page(), page=1) == []
