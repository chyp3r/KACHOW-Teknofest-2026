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
    ) -> ExtractedDocument:
        """Recognise text in a scanned PDF or an image.

        Args:
            content: Raw PDF or image bytes.
            file_name: Original file name, used to decide the input kind.
            mime_type: Declared content type, used to decide the input kind.

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
            pages = await asyncio.to_thread(self._recognize, content, is_pdf)
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
        return ExtractedDocument(
            text=text,
            pages=pages,
            page_count=len(pages),
            extractor=self.name,
            used_ocr=True,
        )

    def _recognize(self, content: bytes, is_pdf: bool) -> list[str]:
        """Run OCR over every page or over a single image.

        Args:
            content: Raw PDF or image bytes.
            is_pdf: Whether the content must be rasterised first.

        Returns:
            Recognised text per page.
        """
        config = f"--psm {self.page_segmentation_mode}"
        if not is_pdf:
            image = Image.open(io.BytesIO(content))
            return [pytesseract.image_to_string(image, lang=self.language, config=config)]

        scale = self.dpi / PDF_POINTS_PER_INCH
        document = pdfium.PdfDocument(content)
        try:
            pages = []
            for page in document:
                bitmap = page.render(scale=scale)
                try:
                    pages.append(
                        pytesseract.image_to_string(
                            bitmap.to_pil(), lang=self.language, config=config
                        )
                    )
                finally:
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
        """Accept PDFs and raster images; reject anything textual."""
        if has_pdf_magic_bytes(content) or mime_type == "application/pdf":
            return True
        if mime_type and mime_type.startswith("image/"):
            return True
        return matches_extension(file_name, IMAGE_EXTENSIONS | PDF_EXTENSIONS)
