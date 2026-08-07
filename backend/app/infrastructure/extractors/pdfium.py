import asyncio
import logging
from typing import Optional

from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
    has_pdf_magic_bytes,
    has_pdf_text_layer,
    matches_extension,
)

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised via patching in tests
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None

PDF_EXTENSIONS = {"pdf"}


class PdfiumExtractor(BaseDocumentExtractor):
    """Pure-Python PDF text extractor built on PDFium via `pypdfium2`.

    Serves as the Java-free safety net behind `OpenDataLoaderExtractor`: it reads
    bytes directly with no temporary file and no JVM, so the pipeline keeps
    working when a Java runtime is unavailable or slow to start. It recovers the
    raw text stream only, without reading order repair or table structure.
    """

    name = "pdfium"

    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        raster_cache: Optional[dict] = None,
    ) -> ExtractedDocument:
        """Extract the embedded text layer of a PDF.

        Args:
            content: The raw PDF bytes.
            file_name: Original file name (unused).
            mime_type: Declared content type (unused).
            raster_cache: Unused; this extractor reads the PDF's own text
                layer and never rasterises anything.

        Returns:
            The extracted text with one entry per page.

        Raises:
            DocumentExtractionError: If pypdfium2 is unavailable or parsing fails.
        """
        if pdfium is None:
            raise DocumentExtractionError(
                "pypdfium2 kurulu değil; PDF metin katmanı okunamadı."
            )

        try:
            pages = await asyncio.to_thread(self._read_pages, content)
        except Exception as exc:
            raise DocumentExtractionError(
                f"PDFium ile PDF okunamadı: {exc}"
            ) from exc

        text = "\n\n".join(pages).strip()
        logger.info(
            "PdfiumExtractor read %d page(s), %d characters.", len(pages), len(text)
        )
        return ExtractedDocument(
            text=text,
            pages=pages,
            page_count=len(pages),
            extractor=self.name,
            used_ocr=False,
        )

    def _read_pages(self, content: bytes) -> list[str]:
        """Read the text layer of every page.

        Args:
            content: The raw PDF bytes.

        Returns:
            Page text in document order.
        """
        document = pdfium.PdfDocument(content)
        try:
            pages = []
            for page in document:
                text_page = page.get_textpage()
                try:
                    pages.append(text_page.get_text_range())
                finally:
                    text_page.close()
                    page.close()
            return pages
        finally:
            document.close()

    def supports(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> bool:
        """Accept PDFs with a text layer; reject genuine scans outright.

        This extractor reads exactly the text layer `has_pdf_text_layer`
        already probed for -- on a genuine scan `_read_pages` would return
        nothing anyway, so skipping it here saves one PDF open-and-iterate
        pass, and lets the chain reach the OCR extractors sooner.
        """
        is_pdf = (
            has_pdf_magic_bytes(content)
            or mime_type == "application/pdf"
            or matches_extension(file_name, PDF_EXTENSIONS)
        )
        return is_pdf and has_pdf_text_layer(content)
