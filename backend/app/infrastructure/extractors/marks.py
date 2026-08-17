"""Best-effort detection of signatures, stamps, and handwritten annotations.

Pure `numpy` + `Pillow` -- both already present in the running image (no
`scipy`, `cv2`, `onnxruntime`, or `torch`; see the design notes this module
was built from). Works directly on the bilevel-ish ink mask of an already-
rasterised page: connected-component analysis over a coarse density grid,
then a small set of shape heuristics (stroke-width variance, baseline
irregularity, aspect ratio, ink density) separate signature/stamp/
handwriting-shaped ink from printed text.

This is a review hint, not a forensic determination, and the module is
explicit about that limit throughout: there is no hand-labelled signature or
stamp dataset for this project's document corpus, so nothing here has a
measured precision or recall -- only detection *counts* against real scans
(see `scripts/evaluate_marks.py`). `check_required_fields` treats a detected
signature as evidence a document is signed; a missed one is a false "eksik
bilgi", not a legal determination that the document is actually unsigned, so
callers must keep presenting this as something for a person to confirm.

Deliberately not a per-pixel connected-component labeller (no
`scipy.ndimage.label`): the page is gridded into `_GRID_CELL_PX`-sized cells
first, ink density is computed per cell (fully vectorised), and only the
resulting few-thousand-cell grid is flood-filled in plain Python -- fast
enough without the dependency, at the cost of losing sub-cell precision,
which this heuristic does not need.
"""

import logging
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised via patching in tests
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:  # pragma: no cover
    from PIL import Image as _PILImage
except ImportError:  # pragma: no cover
    _PILImage = None


class DetectedMark(BaseModel):
    """One ink region flagged as possibly a signature, stamp, or handwritten
    annotation. A heuristic review hint -- see the module docstring."""

    kind: str = Field(description="'signature', 'stamp' veya 'handwriting'.")
    page: int = Field(description="1 tabanlı sayfa numarası.")
    bbox: tuple[int, int, int, int] = Field(
        description=(
            "(x0, y0, x1, y1) -- sayfa genişliği/yüksekliğinden bağımsız "
            "olması için 0-1000 ölçeğine normalize edilmiştir."
        )
    )
    confidence: float = Field(
        description="0.0-1.0 arası kaba güven skoru; adli değil, gözden geçirme amaçlıdır."
    )


#: Grid cell edge length in pixels for the coarse density scan. Small enough
#: to resolve stroke-scale ink at OCR_RENDER_DPI (300), large enough that
#: flood-filling the grid (plain Python, not vectorised) stays fast -- a full
#: 2496x3508 page (this project's typical scanned-page resolution) grids down
#: to roughly 125x175 cells, not 8.7 million pixels.
_GRID_CELL_PX = 20
#: A cell counts as "inked" above this fraction of black pixels.
_CELL_INK_THRESHOLD = 0.08
#: Fixed grayscale threshold separating ink from paper. Not Otsu or any
#: adaptive method -- the corpus this was built for (datasets/resmi_yazisma/
#: 00_gelen_kaynaklar/cevap_yazisi/) is already near-bilevel CCITT-G4 scans,
#: so a fixed threshold is enough and one fewer thing to get wrong.
_INK_GRAY_THRESHOLD = 128
#: A component spanning more than this fraction of the page width is a text
#: line or letterhead run, not a mark -- without this filter every paragraph
#: of body text would be flagged.
_MAX_MARK_WIDTH_FRACTION = 0.5
#: Minimum component size, in grid cells, to consider at all. Filters out
#: isolated printed characters, punctuation, and scan speckle.
_MIN_COMPONENT_CELLS = 6
#: A component this compact (close to square), this dense, and made of many
#: short ink runs (see `_STAMP_MIN_RUN_DENSITY` just below) is treated as a
#: stamp candidate rather than run through the stroke/baseline checks below --
#: an official seal or letterhead crest is fine detailed artwork (a ring of
#: text, a coat of arms), not a line of pen strokes. Measured against the
#: real scanned corpus this module targets (see `scripts/evaluate_marks.py`):
#: a real Turkish resmi mühür is roughly 3.5-4cm (about 1.4-1.6in) across, so
#: `_STAMP_MIN_DIMENSION_PX` is set well under that (still errs toward
#: over-detection rather than missing a smaller or partially-scanned seal),
#: not at it.
_STAMP_ASPECT_RATIO_RANGE = (0.55, 1.8)
_STAMP_MIN_INK_DENSITY = 0.12
#: In pixels, assuming OCR_RENDER_DPI (300) -- every page this module
#: receives is rendered at that density (see BaseDocumentExtractor.extract's
#: raster_cache, keyed by DPI, that TesseractExtractor/OllamaVisionExtractor
#: both populate at exactly that value).
_STAMP_MIN_DIMENSION_PX = 150
#: Minimum mean count of separate horizontal ink runs per 100px of region
#: width (see `_stroke_run_density`) for a stamp-shaped candidate to actually
#: be classified as one. Added after ground-truth labelling (15 real
#: documents, see datasets/resmi_yazisma/ocr_ground_truth.json) found this
#: module reporting 0% signature recall: a real cursive signature can be
#: roughly square and dense enough to satisfy the shape/size checks above on
#: its own (CY-012's actual wet signature over "Yaşar GÜLER" measured
#: aspect ratio 1.69, density 0.121, size 320x540px -- comfortably inside
#: every threshold above), so without this gate the stamp branch intercepted
#: real signatures before the stroke/baseline checks below ever ran. Measured
#: on the real corpus, run density cleanly separates the two populations: a
#: letterhead crest's fine detailed artwork runs 2.18-9.28 (mean ~2.2 for the
#: T.C./ministry emblem in this corpus's own letterhead), while every
#: confirmed real signature that happened to also pass the stamp shape check
#: measured 1.26-1.30 -- a wide gap, not a narrow one, so this is not a
#: fragile cutoff.
_STAMP_MIN_RUN_DENSITY = 2.0
#: Coefficient of variation of stroke width above which ink reads as
#: handwritten (irregular pen pressure/angle) rather than printed (uniform
#: glyph stroke width). On its own this does not separate a short printed
#: phrase from a handwritten mark -- see _MAX_STROKE_RUN_DENSITY, which does.
_HANDWRITING_MIN_STROKE_CV = 0.5
#: Normalised standard deviation of the per-column top-of-ink position above
#: which a region reads as sitting off a shared baseline -- cursive or
#: otherwise irregular, as opposed to printed text's aligned baseline. Same
#: caveat as _HANDWRITING_MIN_STROKE_CV above.
#:
#: Lowered from 0.15 after the same ground-truth labelling found this
#: threshold itself blocking real signatures even once the stamp-interception
#: bug above was fixed: CY-012/CY-009/CY-006's confirmed or highly-probable
#: signatures measured baseline_std 0.119-0.139, all below the original 0.15
#: floor -- a signature's pen strokes still start from a comparatively
#: consistent height (it is a name written along a rough line, unlike a
#: scattered margin annotation), so the general "handwriting" threshold
#: calibrated for annotations was too strict specifically for signatures.
#: Re-verified against the full 45-document corpus after lowering (see
#: scripts/evaluate_marks.py) that this does not reopen the original 24-on-
#: one-page over-triggering problem _MAX_STROKE_RUN_DENSITY was added to fix.
_HANDWRITING_MIN_BASELINE_STD = 0.10
#: Maximum mean count of separate horizontal ink runs per 100px of region
#: width. This is the feature that actually separates a short printed phrase
#: from a handwritten mark -- stroke-width variance and baseline
#: irregularity alone cross their thresholds at word scale too (an ordinary
#: printed word's mix of ascenders/descenders and varying letter widths is
#: enough). Printed text, even a single word, is several distinct glyphs
#: with a gap between each -- many short runs per row. A signature or
#: handwritten mark is typically one or a few continuous connected strokes --
#: far fewer, longer runs relative to its width. Verified against the real
#: scanned corpus this module targets (datasets/resmi_yazisma/
#: 00_gelen_kaynaklar/cevap_yazisi/): every genuinely-printed text fragment
#: on a sample page scored >=1.26, a hand-built cursive test shape scored 1.0.
_MAX_STROKE_RUN_DENSITY = 1.5
#: A signature-shaped region at or below this fraction of page height is
#: classified as a signature (where RYUEHY m.17 places one); the same shape
#: above it is reported as a handwritten annotation instead. The only
#: positional signal used, and a coarse one -- both are the same underlying
#: ink-shape class.
#:
#: Originally 2/3 ("bottom third"), which excluded every real signature this
#: module was tested against: this corpus's letters are short-bodied replies
#: on an otherwise-blank A4 page, so the signature sits wherever the body
#: text happens to end -- measured 0.38-0.65 across 12 confirmed real
#: signatures on this corpus (see datasets/resmi_yazisma/
#: ocr_ground_truth.json), not literally the bottom third of the page.
#: Lowered to 0.35 (comfortably below the lowest confirmed case, 0.38) after
#: specifically checking documents in that positional band that were outside
#: the original labelled sample: every one of them (CY-006/023/028/034) also
#: turned out to be a genuine signature on a template already confirmed
#: elsewhere in the corpus, not a coincidental false positive -- i.e. this
#: is corpus evidence broadened to check for overfitting, not a threshold
#: picked from the original sample alone.
_SIGNATURE_ZONE_START_FRACTION = 0.35


def detect_marks(image, page: int) -> list[DetectedMark]:
    """Best-effort: find signature-, stamp-, and handwriting-shaped ink
    regions on one rasterised page.

    Never raises -- a detector bug must never fail a document upload. Missing
    `numpy`/`Pillow` (guarded imports, matching every other extractor in this
    package) degrades to reporting nothing, the same as any other failure.

    Args:
        image: A rasterised PIL page image, e.g. from the OCR chain's
            `raster_cache` (see `BaseDocumentExtractor.extract`).
        page: 1-based page number, recorded on every returned mark.

    Returns:
        Detected marks, or an empty list on any failure or when nothing
        crosses the size/shape thresholds above.
    """
    if np is None or _PILImage is None:
        return []
    try:
        return _detect_marks(image, page)
    except Exception:
        logger.warning("Mark detection failed for page %d; reporting none.", page, exc_info=True)
        return []


def _detect_marks(image, page: int) -> list[DetectedMark]:
    """The real implementation, unguarded -- see `detect_marks` for the
    try/except boundary every caller actually gets."""
    gray = np.asarray(image.convert("L"))
    height, width = gray.shape
    if height < _GRID_CELL_PX or width < _GRID_CELL_PX:
        return []
    ink = gray < _INK_GRAY_THRESHOLD

    grid = _grid_ink_density(ink, _GRID_CELL_PX) >= _CELL_INK_THRESHOLD
    components = _connected_components(grid)

    marks: list[DetectedMark] = []
    for cells in components:
        if len(cells) < _MIN_COMPONENT_CELLS:
            continue

        row0 = min(r for r, _ in cells)
        row1 = max(r for r, _ in cells) + 1
        col0 = min(c for _, c in cells)
        col1 = max(c for _, c in cells) + 1
        x0, y0 = col0 * _GRID_CELL_PX, row0 * _GRID_CELL_PX
        x1, y1 = min(col1 * _GRID_CELL_PX, width), min(row1 * _GRID_CELL_PX, height)
        if (x1 - x0) > width * _MAX_MARK_WIDTH_FRACTION:
            continue

        region = ink[y0:y1, x0:x1]
        kind, confidence = _classify(region, y_center_fraction=(y0 + y1) / 2 / height)
        if kind is None:
            continue

        marks.append(
            DetectedMark(
                kind=kind,
                page=page,
                bbox=(
                    round(x0 / width * 1000),
                    round(y0 / height * 1000),
                    round(x1 / width * 1000),
                    round(y1 / height * 1000),
                ),
                confidence=confidence,
            )
        )
    return marks


def _grid_ink_density(ink, cell_px: int):
    """Ink fraction per `cell_px` x `cell_px` grid cell, fully vectorised.

    Args:
        ink: Bilevel ink mask (True = ink), full page resolution.
        cell_px: Grid cell edge length in pixels.

    Returns:
        2D array of per-cell ink density, shape
        `(height // cell_px, width // cell_px)`.
    """
    height, width = ink.shape
    rows, cols = height // cell_px, width // cell_px
    # Trim to a whole number of cells -- a partial trailing row/column of a
    # few pixels is not worth padding for.
    trimmed = ink[: rows * cell_px, : cols * cell_px]
    return trimmed.reshape(rows, cell_px, cols, cell_px).mean(axis=(1, 3))


def _connected_components(grid) -> list[list[tuple[int, int]]]:
    """4-connected components of `True` cells in a boolean grid.

    Plain flood fill, not `scipy.ndimage.label` -- correct at the grid's
    scale (tens of thousands of cells, not the millions of pixels a page
    has), which is exactly why detection grids the page first. See the
    module docstring.

    Args:
        grid: Boolean 2D array.

    Returns:
        One list of `(row, col)` cell coordinates per component, in
        discovery order.
    """
    visited = np.zeros_like(grid, dtype=bool)
    rows, cols = grid.shape
    components: list[list[tuple[int, int]]] = []

    for start_r in range(rows):
        for start_c in range(cols):
            if not grid[start_r, start_c] or visited[start_r, start_c]:
                continue
            component: list[tuple[int, int]] = []
            stack = [(start_r, start_c)]
            visited[start_r, start_c] = True
            while stack:
                r, c = stack.pop()
                component.append((r, c))
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if (
                        0 <= nr < rows
                        and 0 <= nc < cols
                        and grid[nr, nc]
                        and not visited[nr, nc]
                    ):
                        visited[nr, nc] = True
                        stack.append((nr, nc))
            components.append(component)
    return components


def _classify(region, y_center_fraction: float) -> tuple[Optional[str], float]:
    """Heuristically classify one ink region. Deliberately coarse -- see the
    module docstring for why there is no accuracy claim attached to this.

    Ordered checks, first match wins:
      1. Roughly square/circular, reasonably dense, at least
         `_STAMP_MIN_DIMENSION_PX` across, AND made of many short ink runs
         (`_STAMP_MIN_RUN_DENSITY`) -> `stamp` (an official seal or
         letterhead crest is fine detailed artwork, not a few pen strokes).
         The run-density gate matters here specifically -- without it, a
         real signature that happens to be roughly square and dense enough
         (a genuine, measured failure mode: see `_STAMP_MIN_RUN_DENSITY`'s
         own comment) passes the same shape test a genuine seal does and is
         intercepted before check 2 ever runs. The size floor still matters
         too: without it a small dense square -- a printed character, a
         logo fragment -- would otherwise pass the same shape test.
      2. Irregular stroke width AND baseline AND low run density (few,
         continuous strokes rather than many discrete glyphs -- see
         `_MAX_STROKE_RUN_DENSITY`; the first two alone are not enough, see
         its docstring) at or below `_SIGNATURE_ZONE_START_FRACTION` of page
         height -> `signature` (where RYUEHY m.17 places one -- see that
         constant's own comment for why this is not literally "the bottom
         third" on this corpus's short-bodied letters).
      3. The same shape elsewhere on the page -> `handwriting` (an
         annotation, a handwritten reference number, a margin note).
      4. Anything else -> not a mark at all; this is what a printed word or
         short text fragment small enough to form its own component looks
         like.

    Args:
        region: The ink mask cropped to one component's bounding box.
        y_center_fraction: The component's vertical centre as a fraction of
            page height (0.0 top, 1.0 bottom) -- the only positional signal
            used, and only to separate `signature` from `handwriting`.

    Returns:
        `(kind, confidence)`, or `(None, 0.0)` when nothing qualifies.
    """
    height, width = region.shape
    if height == 0 or width == 0:
        return None, 0.0

    aspect_ratio = width / height
    ink_density = float(region.mean())
    run_density = _stroke_run_density(region)

    min_ratio, max_ratio = _STAMP_ASPECT_RATIO_RANGE
    if (
        min_ratio <= aspect_ratio <= max_ratio
        and ink_density >= _STAMP_MIN_INK_DENSITY
        and min(height, width) >= _STAMP_MIN_DIMENSION_PX
        and run_density >= _STAMP_MIN_RUN_DENSITY
    ):
        return "stamp", round(min(1.0, 0.4 + ink_density), 2)

    stroke_cv = _stroke_width_cv(region)
    baseline_std = _baseline_std(region)
    if (
        stroke_cv >= _HANDWRITING_MIN_STROKE_CV
        and baseline_std >= _HANDWRITING_MIN_BASELINE_STD
        and run_density <= _MAX_STROKE_RUN_DENSITY
    ):
        confidence = round(min(1.0, 0.3 + stroke_cv / 2), 2)
        if y_center_fraction >= _SIGNATURE_ZONE_START_FRACTION:
            return "signature", confidence
        return "handwriting", confidence

    return None, 0.0


def _horizontal_runs(region) -> list[list[int]]:
    """Lengths of consecutive-ink runs in each non-empty row.

    Shared scan behind both `_stroke_width_cv` (flattens every run's length)
    and `_stroke_run_density` (counts runs per row) -- two different
    questions over the same underlying structure, not two separate scans.

    Args:
        region: Bilevel ink mask, already cropped to one component.

    Returns:
        One list of run lengths per row that carries any ink; rows with no
        ink at all are omitted, not represented as an empty list.
    """
    rows_of_runs: list[list[int]] = []
    for row in region:
        runs: list[int] = []
        count = 0
        for pixel in row:
            if pixel:
                count += 1
            elif count:
                runs.append(count)
                count = 0
        if count:
            runs.append(count)
        if runs:
            rows_of_runs.append(runs)
    return rows_of_runs


def _stroke_width_cv(region) -> float:
    """Coefficient of variation of horizontal ink run lengths.

    Printed glyphs at a given font size have a fairly consistent stroke
    width; handwritten ink varies with pen pressure and angle. Scale-free
    (std over mean), so it does not need to know the page's DPI. On its own
    this does not separate a short printed phrase from a handwritten mark --
    see `_stroke_run_density`, which does; both are required together in
    `_classify`.

    Args:
        region: Bilevel ink mask, already cropped to one component.

    Returns:
        0.0 when there are fewer than two runs to compare (nothing to vary).
    """
    run_lengths = [length for runs in _horizontal_runs(region) for length in runs]
    if len(run_lengths) < 2:
        return 0.0
    arr = np.asarray(run_lengths, dtype=float)
    mean = arr.mean()
    return float(arr.std() / mean) if mean > 0 else 0.0


def _stroke_run_density(region) -> float:
    """Mean count of separate horizontal ink runs per 100px of region width.

    See `_MAX_STROKE_RUN_DENSITY` for the full rationale: this is the
    feature that actually tells a short printed phrase apart from a
    handwritten mark, which stroke-width variance and baseline irregularity
    alone do not at word scale.

    Args:
        region: Bilevel ink mask, already cropped to one component.

    Returns:
        0.0 for a region with no ink at all.
    """
    width = region.shape[1]
    if width == 0:
        return 0.0
    rows_of_runs = _horizontal_runs(region)
    if not rows_of_runs:
        return 0.0
    mean_runs = sum(len(runs) for runs in rows_of_runs) / len(rows_of_runs)
    return mean_runs / (width / 100)


def _baseline_std(region) -> float:
    """Normalised variability of the top-most ink pixel across columns.

    Printed text sitting on a shared baseline has a fairly constant
    top-of-glyph position column to column; cursive or otherwise irregular
    ink does not. Normalised by region height so it is comparable across
    component sizes.

    Args:
        region: Bilevel ink mask, already cropped to one component.

    Returns:
        0.0 when fewer than two columns carry any ink.
    """
    height = region.shape[0]
    if height == 0:
        return 0.0
    tops = []
    for col in region.T:
        rows_with_ink = np.flatnonzero(col)
        if rows_with_ink.size:
            tops.append(rows_with_ink[0])
    if len(tops) < 2:
        return 0.0
    return float(np.std(tops) / height)
