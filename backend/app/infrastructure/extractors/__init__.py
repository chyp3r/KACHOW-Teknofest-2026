from typing import Optional

from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
)
from app.infrastructure.extractors.fallback import FallbackDocumentExtractor
from app.infrastructure.extractors.open_data_loader import OpenDataLoaderExtractor
from app.infrastructure.extractors.pdfium import PdfiumExtractor
from app.infrastructure.extractors.plain_text import PlainTextExtractor
from app.infrastructure.extractors.tesseract import TesseractExtractor
from app.infrastructure.extractors.vision import OllamaVisionExtractor

_document_extractor: Optional[BaseDocumentExtractor] = None


def get_document_extractor() -> BaseDocumentExtractor:
    """Return the shared extraction chain, building it on first use.

    Order matters: already-textual uploads are decoded directly, born-digital PDFs
    go to the layout-aware OpenDataLoader parser, PDFium covers the case where no
    Java runtime is available, and OCR is the last resort for scanned pages.

    Returns:
        The process-wide `FallbackDocumentExtractor`.
    """
    global _document_extractor
    if _document_extractor is None:
        # Shared with `header_repair` below -- the same model/config repairs a
        # scan's header band regardless of whether it was ever tried as a
        # full-page extractor in its own right in this chain.
        vision_extractor = OllamaVisionExtractor()
        _document_extractor = FallbackDocumentExtractor(
            extractors=[
                PlainTextExtractor(),
                OpenDataLoaderExtractor(),
                PdfiumExtractor(),
                TesseractExtractor(),
                # Last resort: far slower than Tesseract but the only thing that
                # survives a degraded photocopy or phone photo.
                vision_extractor,
            ],
            header_repair=vision_extractor,
        )
    return _document_extractor


__all__ = [
    "BaseDocumentExtractor",
    "DocumentExtractionError",
    "ExtractedDocument",
    "FallbackDocumentExtractor",
    "OllamaVisionExtractor",
    "OpenDataLoaderExtractor",
    "PdfiumExtractor",
    "PlainTextExtractor",
    "TesseractExtractor",
    "get_document_extractor",
]
