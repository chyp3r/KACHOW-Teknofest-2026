import asyncio
import io
import logging
from typing import Optional

from app.core.constants import (
    OCR_LANGUAGE,
    OCR_PAGE_SEGMENTATION_MODE,
    OCR_RENDER_DPI,
)
from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
    has_pdf_magic_bytes,
    matches_extension,
)
from app.infrastructure.extractors.marks import detect_marks

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised via patching in tests
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None

try:  # pragma: no cover
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None

try:  # pragma: no cover
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "gif", "webp"}
PDF_EXTENSIONS = {"pdf"}
PDF_POINTS_PER_INCH = 72


class TesseractExtractor(BaseDocumentExtractor):
    """Turkish OCR extractor for scanned PDFs and photographed documents.

    Tesseract reads images only — its input formats come from Leptonica and do not
    include PDF — so PDF input is rasterised with PDFium first at
    `OCR_RENDER_DPI`. Under-scaling is the main cause of poor Turkish character
    recognition, which is why the density is a named constant rather than a
    default.
    """

    name = "tesseract"

    def __init__(
        self,
        language: str = OCR_LANGUAGE,
        dpi: int = OCR_RENDER_DPI,
        page_segmentation_mode: int = OCR_PAGE_SEGMENTATION_MODE,
    ) -> None:
        """Initialise the OCR extractor.

        Args:
            language: Tesseract language pack, e.g. "tur".
            dpi: Rasterisation density used for PDF pages.
            page_segmentation_mode: Tesseract `--psm` value.
        """
        self.language = language
        self.dpi = dpi
        self.page_segmentation_mode = page_segmentation_mode

    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        raster_cache: Optional[dict] = None,
    ) -> ExtractedDocument:
        """Recognise text in a scanned PDF or an image.

        Args:
            content: Raw PDF or image bytes.
            file_name: Original file name, used to decide the input kind.
            mime_type: Declared content type, used to decide the input kind.
            raster_cache: Optional shared cache of already-rasterised pages,
                keyed by DPI (see `BaseDocumentExtractor.extract`). Checked
                before rendering and populated after, so an escalation to
                `OllamaVisionExtractor` at the same DPI reuses these pages
                instead of rasterising the same PDF a second time.

        Returns:
            The recognised text with one entry per page, flagged as OCR output.

        Raises:
            DocumentExtractionError: If a dependency is missing or OCR fails.
        """
        if pytesseract is None or Image is None:
            raise DocumentExtractionError(
                "pytesseract veya Pillow kurulu değil; OCR yapılamadı."
            )

        is_pdf = has_pdf_magic_bytes(content) or mime_type == "application/pdf"
        if is_pdf and pdfium is None:
            raise DocumentExtractionError(
                "pypdfium2 kurulu değil; taranmış PDF OCR için görüntüye çevrilemedi."
            )

        try:
            if not is_pdf:
                images = [await asyncio.to_thread(Image.open, io.BytesIO(content))]
            elif raster_cache is not None and self.dpi in raster_cache:
                images = raster_cache[self.dpi]
                logger.info("Reusing %d already-rasterised page(s) at %d DPI.", len(images), self.dpi)
            else:
                images = await asyncio.to_thread(self._render_pages, content)
                if raster_cache is not None:
                    raster_cache[self.dpi] = images
            # Each pytesseract call blocks on its own `tesseract` subprocess,
            # which releases the GIL for the duration -- concurrent threads
            # here run as genuinely separate OS processes, not serialised by
            # Python. Rendering stays sequential above (pdfium is already
            # fast per page; OCR is the actual cost this parallelises).
            pages = await asyncio.gather(
                *(asyncio.to_thread(self._ocr_image, image) for image in images)
            )
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError(f"OCR sırasında hata oluştu: {exc}") from exc

        text = "\n\n".join(pages).strip()
        logger.info(
            "TesseractExtractor recognised %d page(s), %d characters (lang=%s, dpi=%d).",
            len(pages),
            len(text),
            self.language,
            self.dpi,
        )
        # Best-effort, same rendered pages: detect_marks never raises (see its
        # own docstring), so a detector bug here must never fail an OCR result
        # that otherwise succeeded -- no try/except needed at this call site.
        mark_lists = await asyncio.gather(
            *(
                asyncio.to_thread(detect_marks, image, page_number)
                for page_number, image in enumerate(images, start=1)
            )
        )
        return ExtractedDocument(
            text=text,
            pages=pages,
            page_count=len(pages),
            extractor=self.name,
            used_ocr=True,
            detected_marks=[mark for marks in mark_lists for mark in marks],
        )

    def _render_pages(self, content: bytes) -> list:
        """Rasterise every page of a PDF to a PIL image, in document order.

        Args:
            content: Raw PDF bytes.

        Returns:
            One rendered PIL image per page.
        """
        scale = self.dpi / PDF_POINTS_PER_INCH
        document = pdfium.PdfDocument(content)
        try:
            images = []
            for page in document:
                bitmap = page.render(scale=scale)
                try:
                    images.append(bitmap.to_pil())
                finally:
                    page.close()
            return images
        finally:
            document.close()

    def _ocr_image(self, image) -> str:
        """Run Tesseract over a single page image.

        Args:
            image: A PIL image.

        Returns:
            The recognised text.
        """
        config = f"--psm {self.page_segmentation_mode}"
        return pytesseract.image_to_string(image, lang=self.language, config=config)

    def supports(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> bool:
        """Accept PDFs and raster images; reject anything textual."""
        if has_pdf_magic_bytes(content) or mime_type == "application/pdf":
            return True
        if mime_type and mime_type.startswith("image/"):
            return True
        return matches_extension(file_name, IMAGE_EXTENSIONS | PDF_EXTENSIONS)
