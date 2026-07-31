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

# ---------- Pagination ----------
DEFAULT_PAGE_SIZE: int = 20
MAX_PAGE_SIZE: int = 100

# ---------- AI Workflow ----------
MAX_RETRY_ATTEMPTS: int = 3
AI_WORKFLOW_TIMEOUT_SECONDS: int = 300

# ---------- CORS ----------
CORS_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://localhost:5173",
]

# ---------- Cache ----------
CACHE_TTL_SECONDS: int = 60 * 60  # 1 hour
