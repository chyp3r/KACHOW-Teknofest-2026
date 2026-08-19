"""System-wide constant values shared across the entire application.

For environment-specific or deployment-configurable values, use core/config.py instead.
"""

# ---------- File Uploads ----------
MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024  # 50 MB
ALLOWED_FILE_TYPES: list[str] = [
    "application/pdf",
    "text/plain",
    "application/msword",
    # Photographed or scanned evrak arrive as images and must reach the OCR path.
    "image/png",
    "image/jpeg",
    "image/tiff",
]
ALLOWED_DOCUMENT_EXTENSIONS: list[str] = [
    "pdf",
    "txt",
    "doc",
    "png",
    "jpg",
    "jpeg",
    "tif",
    "tiff",
]

# ---------- Document Text Extraction ----------
# Below this many characters an extraction result is treated as a failure and the
# next extractor in the chain is tried (a scanned PDF yields almost no text).
MIN_EXTRACTED_CHAR_COUNT: int = 200
# Tesseract language pack used for Turkish OCR (`tesseract --list-langs`).
OCR_LANGUAGE: str = "tur"
# Rasterisation density for OCR; under-scaling is the main cause of poor
# Turkish character recognition.
OCR_RENDER_DPI: int = 300
# Below this share of word-length tokens an extraction is treated as unreadable
# and the chain escalates. Character count alone cannot detect OCR garbage:
# a degraded scan yields plenty of characters, just wrong ones.
MIN_TEXT_QUALITY_RATIO: float = 0.6
# Tesseract page segmentation mode 6 = assume a single uniform block of text,
# which matches the block layout of official correspondence.
OCR_PAGE_SEGMENTATION_MODE: int = 6
# Minimum embedded-text characters (across the first few pages) for a PDF to
# count as having a text layer at all, gating OpenDataLoaderExtractor and
# PdfiumExtractor. Deliberately far below MIN_EXTRACTED_CHAR_COUNT: this is a
# cheap "is there anything here" probe, not a quality bar -- a genuine scan
# reads as ~0 characters (maybe a few from an embedded watermark), where any
# born-digital page has real text almost immediately.
TEXT_LAYER_PROBE_MIN_CHARS: int = 20
# How many leading pages the text-layer probe reads before deciding. A scan
# has no text layer on any page, so checking the first few is enough to tell
# it apart from a born-digital PDF even when the document runs much longer.
TEXT_LAYER_PROBE_MAX_PAGES: int = 3
# Fraction of a scanned first page's height treated as the "header band" for
# OllamaVisionExtractor.transcribe_header_band -- covers the letterhead
# through the Konu line on the corpus this was measured against (the 45
# scanned CY-*.pdf under datasets/resmi_yazisma/00_gelen_kaynaklar/cevap_yazisi/).
# No quality signal (header-noise density, quality_ratio) reliably predicts
# which scans need this repair -- calibrating one against that full corpus
# found essentially no correlation with actual outcome (Pearson r=0.036 once
# known parser gaps were controlled for). Applied unconditionally to every
# OCR result instead; a small crop keeps the always-paid cost bounded (~12.6s
# measured, against ~26s for a full page through the same model).
HEADER_BAND_FRACTION: float = 0.28
# How many leading lines of a page's OCR text the header band is assumed to
# cover, for splicing the vision model's cleaner transcription back in. Text
# has no pixel coordinates in this pipeline (ExtractedDocument.pages is a
# flat list[str]), so this is the same line-count approximation used to
# calibrate HEADER_BAND_FRACTION above, not a precise mapping.
HEADER_REPAIR_LINE_COUNT: int = 14
# Minimum count of `count_header_fields` (out of 5: sayi/tarih/konu/muhatap/
# gonderen_kurum) on an extraction's page 1 for FallbackDocumentExtractor to
# accept it outright. `quality_ratio`/`char_count` alone cannot catch this
# failure -- a document can read as fine Turkish prose overall while its
# header block is corrupted or unparseable (observed on real CY-050: 0.85
# quality_ratio, 3316 characters, zero of five header fields recovered).
# Calibrated against the CEILING of what real documents can ever provide, not
# an arbitrary target: parsing all 19 hand-labelled ground-truth documents'
# clean_text through parse_labelled_fields gives a per-document field-count
# distribution of {2: 2 docs, 4: 13, 5: 4} -- `tarih` alone is recoverable on
# only 6 of 19 (many official letterhead templates simply carry no "Tarih"
# label). Requiring more than 2 would force expensive OCR escalation on
# documents whose extraction is already correct. 2 is the highest floor that
# cannot reject a document whose text is genuinely fine.
MIN_HEADER_FIELD_COUNT: int = 2
# Page count above which FallbackDocumentExtractor skips the *full-page*
# vision-model escalation (header-band repair still runs regardless of page
# count -- it only ever touches page 1). Bounds the worst case of the new
# field-triggered escalation at roughly one page's OCR time instead of
# unbounded: a long attachment bundle should not pay full-document vision
# cost to fix header fields that only ever live on page 1.
MAX_OCR_PAGES: int = 3
# Minimum share of a PDF page's area covered by a single embedded image
# object for that page to be treated as image-dominated -- the discriminator
# between a genuine born-digital page (real vector/text content, no
# full-page image) and a page that is actually a scanned raster wrapped in a
# PDF ("Class A": a scanner's own bundled OCR pass writes a junk embedded
# text layer over a full-page image of the original scan, so
# `has_pdf_text_layer` alone cannot tell it apart from a real text layer).
# Measured across 86 real PDFs (50 corpus scans + 36 live uploads): every
# text-layer page from this project's scanner pipeline (`PFUPDF Engine`)
# lands at exactly 1.0 image coverage, and every genuinely born-digital page
# (`ReportLab`) lands at exactly 0.0 -- no document falls between the two, so
# no fine calibration was needed.
FULL_PAGE_IMAGE_MIN_COVERAGE: float = 0.5

# ---------- Pagination ----------
DEFAULT_PAGE_SIZE: int = 20
MAX_PAGE_SIZE: int = 100

# ---------- AI Workflow ----------
# AI_WORKFLOW_TIMEOUT_SECONDS lives in core/config.py (Settings) -- it is
# deployment-configurable, unlike the constants in this file.
MAX_RETRY_ATTEMPTS: int = 3

# ---------- CORS ----------
CORS_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://localhost:5173",
]

# ---------- Cache ----------
CACHE_TTL_SECONDS: int = 60 * 60  # 1 hour
