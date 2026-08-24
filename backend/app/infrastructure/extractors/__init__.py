from typing import Optional

from app.ai.compliance import count_header_fields, has_signature
from app.core.config import settings
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
from app.infrastructure.extractors.vision import EvrenVisionExtractor, OllamaVisionExtractor

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
        # full-page extractor in its own right in this chain. Evren's `vlm`
        # is video-only, so the online mode routes OCR through EvrenVisionExtractor
        # (llm-fast, multimodal chat) instead -- see that class's docstring.
        vision_extractor = (
            OllamaVisionExtractor() if settings.LOCAL_MODE else EvrenVisionExtractor()
        )
        # Online mode swaps only the OCR step: TesseractExtractor (a local
        # binary) is replaced by the vision model (EvrenVisionExtractor,
        # llm-fast) as the chain's OCR fallback -- PlainText/OpenDataLoader/
        # Pdfium stay in the chain unchanged either way, since born-digital
        # text extraction has nothing to do with which OCR provider is
        # configured.
        ocr_step = vision_extractor if not settings.LOCAL_MODE else TesseractExtractor()
        extractors = [
            PlainTextExtractor(),
            OpenDataLoaderExtractor(),
            PdfiumExtractor(),
            ocr_step,
        ]
        if settings.LOCAL_MODE:
            # Last resort: far slower than Tesseract but the only thing that
            # survives a degraded photocopy or phone photo. Online mode has
            # no separate escalation step here -- the vision model already
            # ran as ocr_step above.
            extractors.append(vision_extractor)
        _document_extractor = FallbackDocumentExtractor(
            extractors=extractors,
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
            # `app.ai.compliance.has_signature` -- escalates to a full-page
            # vision transcription instead of the header-band-only crop
            # when the signer's name doesn't parse at all, the one failure
            # mode header-band repair structurally cannot reach (wet
            # signature ink over the printed name, well below the header
            # band). Measured on the real scanned corpus: 4 documents where
            # OpenDataLoader/Tesseract lost or garbled the name entirely,
            # full-page transcription recovered it on all 4.
            signature_probe=has_signature,
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
