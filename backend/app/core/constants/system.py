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
