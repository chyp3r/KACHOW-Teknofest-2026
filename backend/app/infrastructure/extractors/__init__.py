from typing import Optional

from app.ai.compliance import count_header_fields
from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
    is_scanned_text_layer,
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
            # `app.ai.compliance.count_header_fields` -- the only place this
            # infrastructure-layer chain reaches into `app.ai`, and done by
            # injection rather than import inside fallback.py itself so that
            # module stays independent of the AI layer and trivially testable
            # with a bare lambda (see test_extractor.py). Lets the chain
            # escalate past a result that reads as fine Turkish prose overall
            # but whose header block (sayi/tarih/konu/muhatap/gonderen_kurum)
            # didn't actually parse -- quality_ratio alone cannot see that.
            header_field_probe=count_header_fields,
            # `is_scanned_text_layer` -- widens header-band repair to also
            # cover a scanner's own junk OCR text layer sitting over a
            # full-page scan image (Class A), which OpenDataLoader/Pdfium
            # otherwise read exactly like a genuine born-digital text layer.
            scan_text_layer_probe=is_scanned_text_layer,
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
