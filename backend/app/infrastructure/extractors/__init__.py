from typing import Optional

from app.ai.compliance import count_header_fields
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
from app.infrastructure.extractors.vision import EvrenVisionExtractor, OllamaVisionExtractor

_document_extractor: Optional[BaseDocumentExtractor] = None


def get_document_extractor() -> BaseDocumentExtractor:
    """Return the shared, OCR-only (no network vision call) extraction chain,
    building it on first use.

    Order matters: already-textual uploads are decoded directly, born-digital PDFs
    go to the layout-aware OpenDataLoader parser, PDFium covers the case where no
    Java runtime is available, and Tesseract (a local binary, no network call) is
    the last resort for scanned pages.

    Deliberately excludes any vision-model repair/escalation (`header_repair`,
    `scan_text_layer_probe`, `signature_probe` are all `None`) -- those were
    measured to push a single upload from ~14s to ~34s by unconditionally
    triggering a full-page vision transcription call
    (`FallbackDocumentExtractor._maybe_repair_page_one`) whenever a document
    looked like a scan-with-junk-text-layer or had no detectable signature.
    Vision OCR is now opt-in only, via `DocumentService.generate_detailed_analysis`
    (see that method and its `/detailed-analysis` endpoint), which builds its
    own on-demand vision client rather than going through this chain.

    Returns:
        The process-wide `FallbackDocumentExtractor`.
    """
    global _document_extractor
    if _document_extractor is None:
        _document_extractor = FallbackDocumentExtractor(
            extractors=[
                PlainTextExtractor(),
                OpenDataLoaderExtractor(),
                PdfiumExtractor(),
                TesseractExtractor(),
            ],
            # `app.ai.compliance.count_header_fields` -- the only place this
            # infrastructure-layer chain reaches into `app.ai`, and done by
            # injection rather than import inside fallback.py itself so that
            # module stays independent of the AI layer and trivially testable
            # with a bare lambda (see test_extractor.py). Lets the chain
            # escalate past a result that reads as fine Turkish prose overall
            # but whose header block (sayi/tarih/konu/muhatap/gonderen_kurum)
            # didn't actually parse -- quality_ratio alone cannot see that.
            header_field_probe=count_header_fields,
        )
    return _document_extractor


__all__ = [
    "BaseDocumentExtractor",
    "DocumentExtractionError",
    "EvrenVisionExtractor",
    "ExtractedDocument",
    "FallbackDocumentExtractor",
    "OllamaVisionExtractor",
    "OpenDataLoaderExtractor",
    "PdfiumExtractor",
    "PlainTextExtractor",
    "TesseractExtractor",
    "get_document_extractor",
]
