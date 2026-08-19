import re
from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field

from app.core.constants import (
    FULL_PAGE_IMAGE_MIN_COVERAGE,
    TEXT_LAYER_PROBE_MAX_PAGES,
    TEXT_LAYER_PROBE_MIN_CHARS,
)
from app.infrastructure.extractors.marks import DetectedMark

try:  # pragma: no cover - exercised via patching in tests
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None

PDF_MAGIC_BYTES = b"%PDF"

#: Word-ish token: letters and digits, Turkish characters included.
_TOKEN_PATTERN = re.compile(r"[0-9A-Za-zÇĞİÖŞÜçğıöşü]+")
#: Tokens this long or longer are treated as real words rather than OCR noise.
_WORD_MIN_LENGTH = 3


class DocumentExtractionError(Exception):
    """Raised when a document's text cannot be extracted.

    Deliberately a plain exception rather than an `app.api.exceptions` subclass so
    the infrastructure layer stays independent of the HTTP layer. The domain
    service is responsible for translating it into an API exception.
    """


class ExtractedDocument(BaseModel):
    """Text and provenance of a document parsed out of raw uploaded bytes."""

    text: str = Field(description="Belgeden çıkarılan tam metin.")
    pages: list[str] = Field(
        default_factory=list, description="Sayfa sayfa çıkarılan metin parçaları."
    )
    page_count: int = Field(default=0, description="İşlenen sayfa sayısı.")
    extractor: str = Field(
        description="Metni çıkaran bileşenin adı (örn. 'opendataloader')."
    )
    used_ocr: bool = Field(
        default=False,
        description="Metin OCR ile okunduysa true; alan değerleri doğrulanmalıdır.",
    )
    detected_marks: list[DetectedMark] = Field(
        default_factory=list,
        description=(
            "Taranmış sayfalarda tespit edilen olası imza/mühür/el yazısı "
            "bölgeleri. Yalnızca OCR yolundaki çıkarıcılar doldurur "
            "(TesseractExtractor, OllamaVisionExtractor) -- doğrudan metin "
            "katmanı okunan belgeler sayfa hiç görüntüye çevrilmediğinden "
            "boş liste döner. Bir inceleme ipucudur, adli tespit değildir."
        ),
    )

    @property
    def char_count(self) -> int:
        """Number of non-whitespace-stripped characters in the extracted text."""
        return len(self.text.strip())

    @property
    def quality_ratio(self) -> float:
        """Fraction of tokens long enough to be real words rather than OCR noise.

        Character count alone cannot tell a good result from a bad one: OCR run on
        a degraded scan happily returns hundreds of characters of nonsense, which
        clears any length threshold. Failed recognition fragments text into one and
        two character pieces, so the share of word-length tokens separates the two
        cleanly -- measured on this project's corpus, readable Turkish scores about
        0.80 and unusable output about 0.39.

        Returns:
            Ratio between 0.0 and 1.0; 0.0 when there is no text at all.
        """
        tokens = _TOKEN_PATTERN.findall(self.text)
        if not tokens:
            return 0.0
        readable = [token for token in tokens if len(token) >= _WORD_MIN_LENGTH]
        return len(readable) / len(tokens)


class BaseDocumentExtractor(ABC):
    """Abstract text extractor turning raw document bytes into `ExtractedDocument`.

    Takes bytes rather than a path on purpose: both callers already hold bytes
    (`UploadFile.read()` and `BaseStorage.get_file()`), and the S3 storage backend
    has no local path at all. Adapters that wrap a path-based or file-based tool
    are responsible for their own temporary files.
    """

    #: Short identifier recorded in `ExtractedDocument.extractor`.
    name: str = "base"

    @abstractmethod
    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        raster_cache: Optional[dict] = None,
    ) -> ExtractedDocument:
        """Extract text from raw document bytes.

        Args:
            content: The raw document bytes.
            file_name: Original file name, used for extension-based dispatch.
            mime_type: Declared content type, used for dispatch.
            raster_cache: Optional shared cache of already-rasterised PDF
                pages for this one document, keyed by DPI. A scanned PDF is
                rendered by whichever OCR extractor `FallbackDocumentExtractor`
                tries first; if that result is rejected and the chain
                escalates to the next OCR extractor, this is what lets it
                reuse the same rendered pages instead of paying pdfium's
                render cost again. `FallbackDocumentExtractor` creates one
                per top-level `extract()` call and passes it down; extractors
                that never rasterise (`PlainTextExtractor`,
                `OpenDataLoaderExtractor`) ignore it.

        Returns:
            The extracted text along with page breakdown and provenance.

        Raises:
            DocumentExtractionError: If this extractor cannot parse the input.
        """

    def supports(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> bool:
        """Report whether this extractor should be attempted for the given input.

        Guarding the chain matters: without it a plain-text extractor would decode
        PDF bytes into a large blob of replacement characters, clear the minimum
        character threshold, and win over the extractor that can actually read it.

        Args:
            content: The raw document bytes.
            file_name: Original file name.
            mime_type: Declared content type.

        Returns:
            True when this extractor is applicable to the input.
        """
        return True


def has_pdf_magic_bytes(content: bytes) -> bool:
    """Report whether the buffer starts with the PDF file signature.

    Args:
        content: The raw document bytes.

    Returns:
        True when the content is a PDF regardless of the declared MIME type.
    """
    return content[:4] == PDF_MAGIC_BYTES


def has_pdf_text_layer(content: bytes) -> bool:
    """Cheaply report whether a PDF has any meaningful embedded text layer.

    Reads pdfium's native text stream directly -- no OCR, no JVM -- so this
    is fast enough to run before deciding whether `OpenDataLoaderExtractor`
    or `PdfiumExtractor` are worth trying at all. A genuine scan has no text
    layer on any page; a born-digital PDF has real text almost immediately,
    so checking the first few pages tells them apart cheaply even on a long
    document.

    Args:
        content: The raw PDF bytes.

    Returns:
        True when pdfium finds enough embedded text, or when the probe
        itself cannot run at all (pdfium missing, or the PDF fails to open).
        Failing open is deliberate: this function exists purely to skip
        extractors that would waste time on a scan, and a probe that can't
        even open the file is far more informative as "let the real
        extractors report the failure" than as a silent skip.
    """
    if pdfium is None:
        return True
    try:
        document = pdfium.PdfDocument(content)
    except Exception:
        return True

    try:
        found = 0
        for index, page in enumerate(document):
            if index >= TEXT_LAYER_PROBE_MAX_PAGES:
                break
            text_page = page.get_textpage()
            try:
                found += len(text_page.get_text_range().strip())
            finally:
                text_page.close()
                page.close()
        return found >= TEXT_LAYER_PROBE_MIN_CHARS
    except Exception:
        return True
    finally:
        document.close()


def has_full_page_image(content: bytes) -> bool:
    """Report whether a PDF's first page is dominated by a single embedded image.

    The second half of the discriminator that tells a genuinely born-digital
    page apart from a page that merely *carries* a text layer because a
    scanner's own bundled OCR pass wrote one over a full-page raster of the
    original scan ("Class A" -- see `is_scanned_text_layer`).
    `has_pdf_text_layer` alone cannot separate the two; both report real
    text. Measured across 86 real PDFs from this project's own corpus and
    live uploads, this probe's largest-image coverage lands at exactly 1.0
    for every Class-A/scanned page and exactly 0.0 for every genuinely
    born-digital page -- no document falls between the two, so
    `FULL_PAGE_IMAGE_MIN_COVERAGE` needed no fine calibration.

    Args:
        content: The raw PDF bytes.

    Returns:
        True when the largest embedded image object on page 1 covers at
        least `FULL_PAGE_IMAGE_MIN_COVERAGE` of the page area. False
        whenever the probe cannot run at all -- pdfium missing, the PDF
        won't open, or it has no pages. This is the inverse of
        `has_pdf_text_layer`'s fail-open: that probe exists to *skip*
        extractors, so failing open just means "let the real extractor
        report the failure". This probe instead *widens* what gets treated
        as OCR-worthy (see `is_scanned_text_layer`'s only caller,
        `FallbackDocumentExtractor._maybe_repair_header`), so failing closed
        means a file this probe cannot even inspect never spends the extra
        vision-model budget it exists to gate.
    """
    if pdfium is None:
        return False
    try:
        document = pdfium.PdfDocument(content)
    except Exception:
        return False

    try:
        if len(document) == 0:
            return False
        page = document[0]
        try:
            width, height = page.get_width(), page.get_height()
            if not width or not height:
                return False
            page_area = width * height
            coverage = 0.0
            for obj in page.get_objects():
                if obj.type != pdfium.raw.FPDF_PAGEOBJ_IMAGE:
                    continue
                left, bottom, right, top = obj.get_bounds()
                coverage = max(
                    coverage, abs((right - left) * (top - bottom)) / page_area
                )
            return coverage >= FULL_PAGE_IMAGE_MIN_COVERAGE
        finally:
            page.close()
    except Exception:
        return False
    finally:
        document.close()


def is_scanned_text_layer(content: bytes) -> bool:
    """Report whether a PDF's embedded text layer is scanner-origin junk.

    Combines both halves of the Class-A discriminator: a real text layer
    (`has_pdf_text_layer`) sitting over a full-page raster
    (`has_full_page_image`). Either signal alone is insufficient -- a real
    text layer without a full-page image is an ordinary born-digital PDF,
    and a full-page image without a text layer is just a genuine scan with
    no OCR text at all (already routed to the OCR extractors by
    `has_pdf_text_layer` returning False on its own).

    Args:
        content: The raw PDF bytes.

    Returns:
        True only when both signals agree the page carries scanner-origin
        text over a full-page scan image.
    """
    return has_pdf_text_layer(content) and has_full_page_image(content)


def matches_extension(file_name: Optional[str], extensions: set[str]) -> bool:
    """Report whether a file name ends with one of the given extensions.

    Args:
        file_name: File name to inspect; may be None.
        extensions: Lower-case extensions without a leading dot.

    Returns:
        True when the file name carries one of the extensions.
    """
    if not file_name or "." not in file_name:
        return False
    return file_name.rsplit(".", 1)[1].lower() in extensions
