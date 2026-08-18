"""Unit tests for the document text extraction chain."""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document
from PIL import Image, ImageDraw  # real Pillow, not mocked: crop/mark geometry must be genuine

from app.core.constants import MAX_OCR_PAGES
from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
    has_full_page_image,
    has_pdf_magic_bytes,
    has_pdf_text_layer,
    is_scanned_text_layer,
    matches_extension,
)
from app.infrastructure.extractors.fallback import FallbackDocumentExtractor
from app.infrastructure.extractors.open_data_loader import OpenDataLoaderExtractor
from app.infrastructure.extractors.pdfium import PdfiumExtractor
from app.infrastructure.extractors.plain_text import PlainTextExtractor
from app.infrastructure.extractors.tesseract import TesseractExtractor
from app.infrastructure.extractors.vision import OllamaVisionExtractor

TURKISH_TEXT = "Sayı: 12345\nKonu: İzin Talebi\nŞçöğüıİĞÜ"
PDF_BYTES = b"%PDF-1.7\n trailing binary content"


class _FakeExtractor(BaseDocumentExtractor):
    """Test double returning a canned result or raising."""

    def __init__(self, name, text="", error=None, supported=True, used_ocr=False):
        self.name = name
        self._text = text
        self._error = error
        self._supported = supported
        self._used_ocr = used_ocr
        self.call_count = 0

    async def extract(self, content, *, file_name=None, mime_type=None, raster_cache=None):
        self.call_count += 1
        if self._error is not None:
            raise self._error
        return ExtractedDocument(
            text=self._text,
            pages=[self._text],
            page_count=1,
            extractor=self.name,
            used_ocr=self._used_ocr,
        )

    def supports(self, content, *, file_name=None, mime_type=None):
        return self._supported


# ==========================================
# Helper predicates
# ==========================================
def test_has_pdf_magic_bytes_detects_pdf_signature():
    assert has_pdf_magic_bytes(PDF_BYTES) is True
    assert has_pdf_magic_bytes(b"plain text") is False
    assert has_pdf_magic_bytes(b"") is False


def test_matches_extension_is_case_insensitive():
    assert matches_extension("EVRAK.PDF", {"pdf"}) is True
    assert matches_extension("evrak.txt", {"pdf"}) is False
    assert matches_extension("no_extension", {"pdf"}) is False
    assert matches_extension(None, {"pdf"}) is False


@patch("app.infrastructure.extractors.base.pdfium")
def test_has_pdf_text_layer_true_when_pdfium_finds_real_text(mock_pdfium):
    page = MagicMock()
    text_page = MagicMock()
    text_page.get_text_range.return_value = "Sayı: 12345 gerçek metin burada"
    page.get_textpage.return_value = text_page
    document = MagicMock()
    document.__iter__.return_value = iter([page])
    mock_pdfium.PdfDocument.return_value = document

    assert has_pdf_text_layer(PDF_BYTES) is True


@patch("app.infrastructure.extractors.base.pdfium")
def test_has_pdf_text_layer_false_for_a_genuine_scan(mock_pdfium):
    """A scanned page's pdfium text layer is empty -- nothing for
    OpenDataLoader or PDFium to find, which is the whole reason to skip
    them."""
    page = MagicMock()
    text_page = MagicMock()
    text_page.get_text_range.return_value = ""
    page.get_textpage.return_value = text_page
    document = MagicMock()
    document.__iter__.return_value = iter([page, page, page])
    mock_pdfium.PdfDocument.return_value = document

    assert has_pdf_text_layer(PDF_BYTES) is False


@patch("app.infrastructure.extractors.base.pdfium", None)
def test_has_pdf_text_layer_fails_open_without_pdfium():
    assert has_pdf_text_layer(PDF_BYTES) is True


@patch("app.infrastructure.extractors.base.pdfium")
def test_has_pdf_text_layer_fails_open_when_the_pdf_wont_open(mock_pdfium):
    """A probe that can't even open the file should not be the reason a real
    extractor never gets tried -- let that extractor report the failure."""
    mock_pdfium.PdfDocument.side_effect = RuntimeError("corrupt PDF")
    assert has_pdf_text_layer(PDF_BYTES) is True


@patch("app.infrastructure.extractors.base.pdfium")
def test_has_pdf_text_layer_stops_after_the_page_cap(mock_pdfium):
    """A long scanned document must not pay for probing every page."""
    pages = [MagicMock() for _ in range(50)]
    for page in pages:
        text_page = MagicMock()
        text_page.get_text_range.return_value = ""
        page.get_textpage.return_value = text_page
    document = MagicMock()
    document.__iter__.return_value = iter(pages)
    mock_pdfium.PdfDocument.return_value = document

    has_pdf_text_layer(PDF_BYTES)

    checked = sum(1 for page in pages if page.get_textpage.called)
    assert checked <= 3  # TEXT_LAYER_PROBE_MAX_PAGES


def test_extracted_document_char_count_ignores_surrounding_whitespace():
    document = ExtractedDocument(text="  abc  ", extractor="test")
    assert document.char_count == 3


def _mock_page_with_image(mock_pdfium, coverage: float, width=1000.0, height=1000.0):
    """Build a mock page whose single embedded image covers `coverage` of the
    page area, wired against the same `pdfium.raw.FPDF_PAGEOBJ_IMAGE`
    sentinel `has_full_page_image` reads."""
    mock_pdfium.raw.FPDF_PAGEOBJ_IMAGE = 3
    page = MagicMock()
    page.get_width.return_value = width
    page.get_height.return_value = height
    image_obj = MagicMock()
    image_obj.type = 3
    side = (coverage * width * height) ** 0.5
    image_obj.get_bounds.return_value = (0.0, 0.0, side, side)
    page.get_objects.return_value = [image_obj]
    return page


@patch("app.infrastructure.extractors.base.pdfium")
def test_has_full_page_image_true_at_full_coverage(mock_pdfium):
    page = _mock_page_with_image(mock_pdfium, coverage=1.0)
    document = MagicMock()
    document.__len__.return_value = 1
    document.__getitem__.return_value = page
    mock_pdfium.PdfDocument.return_value = document

    assert has_full_page_image(PDF_BYTES) is True


@patch("app.infrastructure.extractors.base.pdfium")
def test_has_full_page_image_false_with_no_embedded_images(mock_pdfium):
    """A born-digital page: real vector/text content objects, no image."""
    mock_pdfium.raw.FPDF_PAGEOBJ_IMAGE = 3
    page = MagicMock()
    page.get_width.return_value = 1000.0
    page.get_height.return_value = 1000.0
    text_obj = MagicMock()
    text_obj.type = 1  # not FPDF_PAGEOBJ_IMAGE
    page.get_objects.return_value = [text_obj]
    document = MagicMock()
    document.__len__.return_value = 1
    document.__getitem__.return_value = page
    mock_pdfium.PdfDocument.return_value = document

    assert has_full_page_image(PDF_BYTES) is False


@patch("app.infrastructure.extractors.base.pdfium")
def test_has_full_page_image_false_below_coverage_threshold(mock_pdfium):
    """A small embedded logo/watermark must not read as a full-page scan."""
    page = _mock_page_with_image(mock_pdfium, coverage=0.05)
    document = MagicMock()
    document.__len__.return_value = 1
    document.__getitem__.return_value = page
    mock_pdfium.PdfDocument.return_value = document

    assert has_full_page_image(PDF_BYTES) is False


@patch("app.infrastructure.extractors.base.pdfium", None)
def test_has_full_page_image_fails_closed_without_pdfium():
    """Inverse of has_pdf_text_layer's fail-open: this probe only ever
    widens what gets treated as OCR-worthy, so an uninspectable file must
    not spend the extra vision-model budget it exists to gate."""
    assert has_full_page_image(PDF_BYTES) is False


@patch("app.infrastructure.extractors.base.pdfium")
def test_has_full_page_image_fails_closed_when_the_pdf_wont_open(mock_pdfium):
    mock_pdfium.PdfDocument.side_effect = RuntimeError("corrupt PDF")
    assert has_full_page_image(PDF_BYTES) is False


@patch("app.infrastructure.extractors.base.pdfium")
def test_has_full_page_image_fails_closed_with_no_pages(mock_pdfium):
    document = MagicMock()
    document.__len__.return_value = 0
    mock_pdfium.PdfDocument.return_value = document

    assert has_full_page_image(PDF_BYTES) is False


@patch("app.infrastructure.extractors.base.has_full_page_image", return_value=True)
@patch("app.infrastructure.extractors.base.has_pdf_text_layer", return_value=True)
def test_is_scanned_text_layer_true_when_both_signals_agree(mock_text, mock_image):
    """Class A: a scanner's own OCR pass writes a junk text layer over a
    full-page raster of the original scan."""
    assert is_scanned_text_layer(PDF_BYTES) is True


@patch("app.infrastructure.extractors.base.has_full_page_image", return_value=False)
@patch("app.infrastructure.extractors.base.has_pdf_text_layer", return_value=True)
def test_is_scanned_text_layer_false_for_born_digital(mock_text, mock_image):
    assert is_scanned_text_layer(PDF_BYTES) is False


@patch("app.infrastructure.extractors.base.has_full_page_image", return_value=True)
@patch("app.infrastructure.extractors.base.has_pdf_text_layer", return_value=False)
def test_is_scanned_text_layer_false_for_a_genuine_scan_with_no_text_layer(mock_text, mock_image):
    """A full-page image alone isn't enough -- a genuine scan (Class B, no
    text layer at all) must not be misread as Class A."""
    assert is_scanned_text_layer(PDF_BYTES) is False


# ==========================================
# PlainTextExtractor
# ==========================================
@pytest.mark.asyncio
async def test_plain_text_extractor_preserves_turkish_characters():
    extractor = PlainTextExtractor()
    result = await extractor.extract(TURKISH_TEXT.encode("utf-8"))
    assert result.text == TURKISH_TEXT
    assert result.extractor == "plain_text"
    assert result.used_ocr is False
    assert result.page_count == 1


@pytest.mark.asyncio
async def test_plain_text_extractor_tolerates_undecodable_bytes():
    extractor = PlainTextExtractor()
    result = await extractor.extract(b"\xff\xfe gecerli metin")
    assert "gecerli metin" in result.text


def test_plain_text_extractor_rejects_pdf_bytes():
    """Guards the chain: a PDF must never be decoded as text."""
    extractor = PlainTextExtractor()
    assert extractor.supports(PDF_BYTES, mime_type="application/pdf") is False
    assert extractor.supports(PDF_BYTES, file_name="evrak.pdf") is False


def test_plain_text_extractor_accepts_text_mime_and_extension():
    extractor = PlainTextExtractor()
    assert extractor.supports(b"abc", mime_type="text/plain") is True
    assert extractor.supports(b"abc", file_name="evrak.txt") is True


# ==========================================
# OpenDataLoaderExtractor
# ==========================================
@pytest.mark.asyncio
@patch("app.infrastructure.extractors.open_data_loader.OpenDataLoaderPDFLoader")
async def test_open_data_loader_extractor_joins_pages(mock_loader_class):
    mock_loader = MagicMock()
    mock_loader.load.return_value = [
        Document(page_content="birinci sayfa", metadata={"page": 1}),
        Document(page_content="ikinci sayfa", metadata={"page": 2}),
    ]
    mock_loader_class.return_value = mock_loader

    extractor = OpenDataLoaderExtractor()
    result = await extractor.extract(PDF_BYTES, file_name="evrak.pdf")

    assert result.page_count == 2
    assert result.pages == ["birinci sayfa", "ikinci sayfa"]
    assert result.text == "birinci sayfa\n\nikinci sayfa"
    assert result.extractor == "opendataloader"
    assert result.used_ocr is False


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.open_data_loader.OpenDataLoaderPDFLoader")
async def test_open_data_loader_extractor_cleans_up_temp_file(mock_loader_class):
    """The scratch directory holding the PDF must not outlive the call."""
    captured = {}

    def capture(**kwargs):
        captured["path"] = kwargs["file_path"]
        loader = MagicMock()
        loader.load.return_value = [Document(page_content="metin", metadata={})]
        return loader

    mock_loader_class.side_effect = capture
    await OpenDataLoaderExtractor().extract(PDF_BYTES)

    import os

    assert not os.path.exists(captured["path"])


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.open_data_loader.OpenDataLoaderPDFLoader", None)
async def test_open_data_loader_extractor_raises_without_dependency():
    with pytest.raises(DocumentExtractionError) as exc_info:
        await OpenDataLoaderExtractor().extract(PDF_BYTES)
    assert "kurulu değil" in str(exc_info.value)


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.open_data_loader.OpenDataLoaderPDFLoader")
async def test_open_data_loader_extractor_wraps_loader_failure(mock_loader_class):
    mock_loader_class.side_effect = RuntimeError("JVM baslatilamadi")
    with pytest.raises(DocumentExtractionError) as exc_info:
        await OpenDataLoaderExtractor().extract(PDF_BYTES)
    assert "okunamadı" in str(exc_info.value)


def test_open_data_loader_extractor_supports_pdf_only():
    extractor = OpenDataLoaderExtractor()
    assert extractor.supports(PDF_BYTES) is True
    assert extractor.supports(b"abc", mime_type="application/pdf") is True
    assert extractor.supports(b"abc", mime_type="text/plain") is False


@patch("app.infrastructure.extractors.open_data_loader.has_pdf_text_layer", return_value=False)
def test_open_data_loader_extractor_rejects_a_pdf_with_no_text_layer(mock_probe):
    """A genuine scan has nothing for OpenDataLoader to find -- skip it
    before paying its JVM startup cost, not after."""
    assert OpenDataLoaderExtractor().supports(PDF_BYTES) is False


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.open_data_loader.OpenDataLoaderPDFLoader")
async def test_open_data_loader_strips_markdown_heading_markers(mock_loader_class):
    """`output_format="markdown"` injects heading syntax onto ordinary header
    lines (e.g. "##### TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA"), which then
    leaks verbatim into a parsed field value -- observed on real CY-034/
    ANKARA_BSB documents. The '#'s are this extractor's own formatting
    artefact, not part of the document, so they are stripped here rather than
    downstream in the parser, cleaning the text for every consumer at once."""
    mock_loader = MagicMock()
    mock_loader.load.return_value = [
        Document(
            page_content="##### TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA\nSayı : 123",
            metadata={},
        ),
        Document(page_content="### Konu : Soru Önergesi", metadata={}),
    ]
    mock_loader_class.return_value = mock_loader

    result = await OpenDataLoaderExtractor().extract(PDF_BYTES)

    assert result.pages[0] == "TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA\nSayı : 123"
    assert result.pages[1] == "Konu : Soru Önergesi"
    assert "#" not in result.text


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.open_data_loader.OpenDataLoaderPDFLoader")
async def test_open_data_loader_leaves_non_heading_hashes_untouched(mock_loader_class):
    """Only leading heading markers are formatting noise. A table row's pipes
    and a genuine '#' inside body text (not a run of 1-6 at line start
    followed by a space) must survive unchanged -- this is a targeted strip,
    not a blanket '#' removal."""
    mock_loader = MagicMock()
    mock_loader.load.return_value = [
        Document(page_content="| Ad | Soyad |\n| --- | --- |\n| Ali | Veli |", metadata={}),
        Document(page_content="Numara #12 dosyaya eklendi.", metadata={}),
    ]
    mock_loader_class.return_value = mock_loader

    result = await OpenDataLoaderExtractor().extract(PDF_BYTES)

    assert result.pages[0] == "| Ad | Soyad |\n| --- | --- |\n| Ali | Veli |"
    assert result.pages[1] == "Numara #12 dosyaya eklendi."


# ==========================================
# PdfiumExtractor
# ==========================================
@pytest.mark.asyncio
@patch("app.infrastructure.extractors.pdfium.pdfium")
async def test_pdfium_extractor_reads_text_layer(mock_pdfium):
    text_page = MagicMock()
    text_page.get_text_range.return_value = "pdfium metni"
    page = MagicMock()
    page.get_textpage.return_value = text_page
    document = MagicMock()
    document.__iter__.return_value = iter([page])
    mock_pdfium.PdfDocument.return_value = document

    result = await PdfiumExtractor().extract(PDF_BYTES)

    assert result.text == "pdfium metni"
    assert result.extractor == "pdfium"
    assert result.used_ocr is False
    document.close.assert_called_once()


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.pdfium.pdfium", None)
async def test_pdfium_extractor_raises_without_dependency():
    with pytest.raises(DocumentExtractionError):
        await PdfiumExtractor().extract(PDF_BYTES)


@patch("app.infrastructure.extractors.pdfium.has_pdf_text_layer", return_value=False)
def test_pdfium_extractor_rejects_a_pdf_with_no_text_layer(mock_probe):
    assert PdfiumExtractor().supports(PDF_BYTES) is False


# ==========================================
# TesseractExtractor
# ==========================================
@pytest.mark.asyncio
@patch("app.infrastructure.extractors.tesseract.Image")
@patch("app.infrastructure.extractors.tesseract.pytesseract")
async def test_tesseract_extractor_uses_turkish_language_for_images(
    mock_pytesseract, mock_image
):
    mock_pytesseract.image_to_string.return_value = "taranmis metin"

    result = await TesseractExtractor().extract(
        b"\x89PNG fake", mime_type="image/png"
    )

    assert result.text == "taranmis metin"
    assert result.used_ocr is True
    assert result.extractor == "tesseract"
    assert mock_pytesseract.image_to_string.call_args.kwargs["lang"] == "tur"
    assert "--psm 6" in mock_pytesseract.image_to_string.call_args.kwargs["config"]


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.tesseract.pdfium")
@patch("app.infrastructure.extractors.tesseract.Image")
@patch("app.infrastructure.extractors.tesseract.pytesseract")
async def test_tesseract_extractor_rasterizes_pdf_at_300_dpi(
    mock_pytesseract, mock_image, mock_pdfium
):
    """Tesseract cannot read PDF, so pages must be rendered to images first."""
    mock_pytesseract.image_to_string.return_value = "ocr sayfasi"
    page = MagicMock()
    document = MagicMock()
    document.__iter__.return_value = iter([page])
    mock_pdfium.PdfDocument.return_value = document

    result = await TesseractExtractor().extract(PDF_BYTES)

    assert result.used_ocr is True
    assert result.text == "ocr sayfasi"
    # 300 DPI over PDF's native 72 points-per-inch.
    assert page.render.call_args.kwargs["scale"] == pytest.approx(300 / 72)


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.tesseract.pytesseract", None)
async def test_tesseract_extractor_raises_without_dependency():
    with pytest.raises(DocumentExtractionError):
        await TesseractExtractor().extract(b"\x89PNG", mime_type="image/png")


def test_tesseract_extractor_supports_images_and_pdf_but_not_text():
    extractor = TesseractExtractor()
    assert extractor.supports(b"x", mime_type="image/png") is True
    assert extractor.supports(PDF_BYTES) is True
    assert extractor.supports(b"x", file_name="evrak.tiff") is True
    assert extractor.supports(b"x", mime_type="text/plain") is False


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.tesseract.pdfium")
@patch("app.infrastructure.extractors.tesseract.pytesseract")
async def test_tesseract_extractor_ocrs_pages_concurrently_not_one_at_a_time(
    mock_pytesseract, mock_pdfium
):
    """Regression: pages used to OCR strictly one at a time inside a single
    background thread, so a 10-page scan paid 10x pytesseract's latency in
    series. Each page's call here blocks on a barrier that only releases
    once every page's call has actually started -- a sequential
    implementation deadlocks (the first call waits forever for a second
    call that can't start until the first returns), where a genuinely
    concurrent one releases immediately."""
    import threading

    page_count = 4
    barrier = threading.Barrier(page_count, timeout=2)

    def _blocking_ocr(image, lang, config):
        barrier.wait()
        return "sayfa metni"

    mock_pytesseract.image_to_string.side_effect = _blocking_ocr

    pages = [MagicMock() for _ in range(page_count)]
    document = MagicMock()
    document.__iter__.return_value = iter(pages)
    mock_pdfium.PdfDocument.return_value = document

    result = await TesseractExtractor().extract(PDF_BYTES)

    assert result.page_count == page_count
    assert mock_pytesseract.image_to_string.call_count == page_count


# ==========================================
# Shared raster cache (Tesseract -> Vision escalation)
# ==========================================
@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.pdfium")
@patch("app.infrastructure.extractors.tesseract.pdfium")
@patch("app.infrastructure.extractors.tesseract.Image")
@patch("app.infrastructure.extractors.tesseract.pytesseract")
async def test_tesseract_populates_the_raster_cache_for_vision_to_reuse(
    mock_pytesseract, mock_image, mock_tesseract_pdfium, mock_vision_pdfium
):
    """Regression: a scanned PDF used to be rasterised once by Tesseract
    (discarded once its result was rejected) and again by the vision model
    -- the exact escalation FallbackDocumentExtractor performs on a degraded
    scan. Sharing one raster_cache dict between the two calls means the
    second extractor must never touch pdfium.PdfDocument at all."""
    mock_pytesseract.image_to_string.return_value = "zayif metin"
    page = MagicMock()
    document = MagicMock()
    document.__iter__.return_value = iter([page])
    mock_tesseract_pdfium.PdfDocument.return_value = document

    cache = {}
    await TesseractExtractor().extract(PDF_BYTES, raster_cache=cache)

    assert mock_tesseract_pdfium.PdfDocument.call_count == 1
    assert list(cache.keys()) == [300]  # OCR_RENDER_DPI default
    assert len(cache[300]) == 1

    import json as _json

    class _Resp:
        def read(self_inner):
            return _json.dumps({"response": "iyi metin"}).encode()

        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *args):
            return False

    with patch("app.infrastructure.extractors.vision.urllib.request.urlopen", return_value=_Resp()):
        result = await OllamaVisionExtractor(model="test-model").extract(
            PDF_BYTES, raster_cache=cache
        )

    assert mock_vision_pdfium.PdfDocument.call_count == 0
    assert result.text == "iyi metin"


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.tesseract.pdfium")
@patch("app.infrastructure.extractors.tesseract.Image")
@patch("app.infrastructure.extractors.tesseract.pytesseract")
async def test_a_different_dpi_does_not_reuse_another_dpis_cache_entry(
    mock_pytesseract, mock_image, mock_pdfium
):
    mock_pytesseract.image_to_string.return_value = "metin"
    page = MagicMock()
    document = MagicMock()
    document.__iter__.return_value = iter([page])
    mock_pdfium.PdfDocument.return_value = document

    cache = {150: [MagicMock()]}  # already warm at a different DPI
    await TesseractExtractor(dpi=300).extract(PDF_BYTES, raster_cache=cache)

    # 300 isn't in the cache yet, so this must render, not reuse 150's pages.
    mock_pdfium.PdfDocument.assert_called_once()
    assert 300 in cache


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.tesseract.pdfium")
@patch("app.infrastructure.extractors.tesseract.Image")
@patch("app.infrastructure.extractors.tesseract.pytesseract")
async def test_no_cache_still_works_exactly_as_before(mock_pytesseract, mock_image, mock_pdfium):
    """raster_cache is optional -- a caller that never passes one (or passes
    None) must see identical behaviour to before this parameter existed."""
    mock_pytesseract.image_to_string.return_value = "metin"
    page = MagicMock()
    document = MagicMock()
    document.__iter__.return_value = iter([page])
    mock_pdfium.PdfDocument.return_value = document

    result = await TesseractExtractor().extract(PDF_BYTES)

    assert result.text == "metin"


# ==========================================
# FallbackDocumentExtractor
# ==========================================
@pytest.mark.asyncio
async def test_fallback_returns_first_sufficient_result_without_calling_rest():
    first = _FakeExtractor("first", text="x" * 250)
    second = _FakeExtractor("second", text="y" * 250)
    chain = FallbackDocumentExtractor([first, second], min_char_count=200)

    result = await chain.extract(b"data")

    assert result.extractor == "first"
    assert second.call_count == 0


@pytest.mark.asyncio
async def test_fallback_skips_result_below_threshold():
    thin = _FakeExtractor("thin", text="short")
    rich = _FakeExtractor("rich", text="x" * 250)
    chain = FallbackDocumentExtractor([thin, rich], min_char_count=200)

    result = await chain.extract(b"data")

    assert result.extractor == "rich"
    assert thin.call_count == 1


@pytest.mark.asyncio
async def test_fallback_returns_best_effort_when_all_below_threshold():
    tiny = _FakeExtractor("tiny", text="ab")
    bigger = _FakeExtractor("bigger", text="abcdef")
    chain = FallbackDocumentExtractor([tiny, bigger], min_char_count=200)

    result = await chain.extract(b"data")

    assert result.extractor == "bigger"


@pytest.mark.asyncio
async def test_fallback_skips_failing_extractor():
    broken = _FakeExtractor("broken", error=DocumentExtractionError("bozuk"))
    healthy = _FakeExtractor("healthy", text="x" * 250)
    chain = FallbackDocumentExtractor([broken, healthy], min_char_count=200)

    result = await chain.extract(b"data")

    assert result.extractor == "healthy"


@pytest.mark.asyncio
async def test_fallback_skips_unsupported_extractor():
    unsupported = _FakeExtractor("unsupported", text="x" * 250, supported=False)
    supported = _FakeExtractor("supported", text="y" * 250)
    chain = FallbackDocumentExtractor([unsupported, supported], min_char_count=200)

    result = await chain.extract(b"data")

    assert result.extractor == "supported"
    assert unsupported.call_count == 0


@pytest.mark.asyncio
async def test_fallback_raises_when_all_extractors_fail():
    chain = FallbackDocumentExtractor(
        [_FakeExtractor("a", error=RuntimeError("bir")),
         _FakeExtractor("b", error=RuntimeError("iki"))],
        min_char_count=200,
    )
    with pytest.raises(DocumentExtractionError):
        await chain.extract(b"data")


@pytest.mark.asyncio
async def test_fallback_raises_when_no_extractor_supports_input():
    chain = FallbackDocumentExtractor(
        [_FakeExtractor("a", text="x" * 250, supported=False)], min_char_count=200
    )
    with pytest.raises(DocumentExtractionError) as exc_info:
        await chain.extract(b"data")
    assert "desteği bulunmuyor" in str(exc_info.value)


# ------------------------------------------------------------------------
# Field-aware acceptance -- `quality_ratio` is a document-wide prose
# average and cannot see header damage (measured on a real document: 0.85
# quality_ratio, zero of five prescribed header fields recovered). These
# tests use a bare lambda as `header_field_probe` rather than the real
# `count_header_fields`, matching how `header_repair` is already injected
# rather than imported -- this module must not depend on `app.ai`.
# ------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_chain_escalates_past_a_result_with_too_few_header_fields():
    thin_header = _FakeExtractor("thin_header", text="x" * 250)
    rich_header = _FakeExtractor("rich_header", text="y" * 250)
    probe = lambda text: 1 if text.startswith("x") else 2  # noqa: E731
    chain = FallbackDocumentExtractor(
        [thin_header, rich_header],
        min_char_count=200,
        header_field_probe=probe,
        min_header_field_count=2,
    )

    result = await chain.extract(b"data")

    assert thin_header.call_count == 1
    assert result.extractor == "rich_header"


@pytest.mark.asyncio
async def test_chain_accepts_a_result_right_at_the_header_field_floor():
    at_floor = _FakeExtractor("at_floor", text="x" * 250)
    never_reached = _FakeExtractor("never_reached", text="y" * 250)
    chain = FallbackDocumentExtractor(
        [at_floor, never_reached],
        min_char_count=200,
        header_field_probe=lambda text: 2,  # noqa: E731
        min_header_field_count=2,
    )

    result = await chain.extract(b"data")

    assert result.extractor == "at_floor"
    assert never_reached.call_count == 0


@pytest.mark.asyncio
async def test_header_field_criterion_is_inert_without_a_probe():
    """A caller that doesn't inject `header_field_probe` (every caller before
    this parameter existed) gets exactly today's char/quality-only
    acceptance -- this criterion must never reject anything on its own."""
    only = _FakeExtractor("only", text="x" * 250)
    chain = FallbackDocumentExtractor([only], min_char_count=200)

    result = await chain.extract(b"data")

    assert result.extractor == "only"


@pytest.mark.asyncio
async def test_best_effort_ranks_by_header_field_count_before_readability():
    """When nothing clears char/quality, the candidate that recovered more
    header fields wins even over a more 'readable' one."""
    more_fields = _FakeExtractor("more_fields", text=GARBAGE_OCR)
    fewer_fields = _FakeExtractor("fewer_fields", text=READABLE_OCR)
    probe = lambda text: 3 if text == GARBAGE_OCR else 1  # noqa: E731
    chain = FallbackDocumentExtractor(
        [more_fields, fewer_fields],
        min_char_count=10_000,  # nothing clears the length threshold
        header_field_probe=probe,
    )

    result = await chain.extract(b"data")

    assert result.extractor == "more_fields"


@pytest.mark.asyncio
async def test_best_effort_still_falls_back_to_readability_when_field_counts_tie():
    """Equal field counts (including the universal 0 with no probe
    configured) preserve the pre-existing tie-break rule exactly."""
    long_garbage = _FakeExtractor("long_garbage", text=GARBAGE_OCR * 4)
    short_clean = _FakeExtractor("short_clean", text="Sayı bilgisi bulunmaktadır")
    chain = FallbackDocumentExtractor(
        [long_garbage, short_clean],
        min_char_count=10_000,
        header_field_probe=lambda text: 0,  # noqa: E731 -- tie on every candidate
    )

    result = await chain.extract(b"data")

    assert result.extractor == "short_clean"


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.open_data_loader.OpenDataLoaderPDFLoader")
async def test_open_data_loader_preserves_line_breaks(mock_loader_class):
    """Header line structure is load-bearing: collapsing it breaks field extraction."""
    mock_loader = MagicMock()
    mock_loader.load.return_value = [Document(page_content="metin", metadata={})]
    mock_loader_class.return_value = mock_loader

    await OpenDataLoaderExtractor().extract(PDF_BYTES)

    assert mock_loader_class.call_args.kwargs["keep_line_breaks"] is True


# ==========================================
# Readability signal and escalation
# ==========================================
GARBAGE_OCR = (
    "e ee m ; ay MN a\n, e. Personel Genel esi # Lei a , Di m RE e Ni yi vel\n"
    "Ke Beyi Sefa 14 İL008.07 GATS2 Per ler ae AŞ e\nVU Dİ Talih 1203:2028 | >. İY Ea ayl 0"
)
READABLE_OCR = (
    "T.C.\nÖRNEK BAKANLIĞI\nPersonel Genel Müdürlüğü\n\n"
    "Sayı : E-11111111-903.07.02-4752\nTarih : 12.03.2026\n"
    "Konu : Yıllık İzin Talebinin Değerlendirilmesi"
)


def test_quality_ratio_separates_readable_text_from_ocr_garbage():
    readable = ExtractedDocument(text=READABLE_OCR, extractor="t").quality_ratio
    garbage = ExtractedDocument(text=GARBAGE_OCR, extractor="t").quality_ratio
    assert readable > 0.6
    assert garbage < 0.6


def test_quality_ratio_of_empty_text_is_zero():
    assert ExtractedDocument(text="   ", extractor="t").quality_ratio == 0.0


@pytest.mark.asyncio
async def test_chain_escalates_past_long_but_unreadable_output():
    """The case that motivated the signal: OCR on a degraded scan returns plenty
    of characters, so a length-only threshold would accept the garbage."""
    noisy = _FakeExtractor("noisy", text=GARBAGE_OCR * 6)
    clean = _FakeExtractor("clean", text=READABLE_OCR * 6)
    chain = FallbackDocumentExtractor([noisy, clean], min_char_count=200)

    result = await chain.extract(b"data")

    assert noisy.call_count == 1
    assert result.extractor == "clean"


@pytest.mark.asyncio
async def test_best_effort_prefers_readability_over_length():
    """A short clean result beats a long unreadable one when nothing qualifies."""
    long_garbage = _FakeExtractor("long_garbage", text=GARBAGE_OCR * 4)
    short_clean = _FakeExtractor("short_clean", text="Sayı bilgisi bulunmaktadır")
    chain = FallbackDocumentExtractor(
        [long_garbage, short_clean], min_char_count=10_000
    )

    result = await chain.extract(b"data")

    assert result.extractor == "short_clean"


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.urllib.request.urlopen")
async def test_vision_extractor_transcribes_an_image(mock_urlopen):
    import json as _json

    class _Resp:
        def read(self_inner):
            return _json.dumps({"response": "T.C.\nÖRNEK BAKANLIĞI"}).encode()

        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *args):
            return False

    mock_urlopen.return_value = _Resp()

    result = await OllamaVisionExtractor(model="glm-ocr:latest").extract(
        b"\x89PNG fake", mime_type="image/png"
    )

    assert result.text == "T.C.\nÖRNEK BAKANLIĞI"
    assert result.used_ocr is True
    assert result.extractor == "ollama_vision"


def test_vision_extractor_supports_images_and_pdf_but_not_text():
    extractor = OllamaVisionExtractor()
    assert extractor.supports(b"x", mime_type="image/png") is True
    assert extractor.supports(PDF_BYTES) is True
    assert extractor.supports(b"x", mime_type="text/plain") is False


# ==========================================
# render_first_page -- used by header-band repair (fallback.py) to rasterise
# page 1 for a result whose extractor never renders anything itself (e.g.
# OpenDataLoader/Pdfium reading a Class-A scanner text layer). Only page 1 is
# ever rendered here, unlike `_render_pages`, to keep this always-paid cost
# bounded to roughly one page regardless of document length.
# ==========================================
@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.pdfium")
async def test_render_first_page_renders_only_the_first_page(mock_pdfium):
    rendered = Image.new("L", (10, 10))
    bitmap = MagicMock()
    bitmap.to_pil.return_value = rendered
    page1 = MagicMock()
    page1.render.return_value = bitmap
    document = MagicMock()
    document.__len__.return_value = 3
    document.__getitem__.return_value = page1
    mock_pdfium.PdfDocument.return_value = document

    result = await OllamaVisionExtractor().render_first_page(PDF_BYTES)

    assert result is rendered
    document.__getitem__.assert_called_once_with(0)


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.pdfium")
async def test_render_first_page_returns_none_with_no_pages(mock_pdfium):
    document = MagicMock()
    document.__len__.return_value = 0
    mock_pdfium.PdfDocument.return_value = document

    assert await OllamaVisionExtractor().render_first_page(PDF_BYTES) is None


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.pdfium")
async def test_render_first_page_returns_none_when_the_pdf_wont_open(mock_pdfium):
    """A raw scanned image upload (not a PDF at all) never reaches this via a
    real chain -- header repair's own `used_ocr` check would already have
    routed it through an OCR extractor that populates raster_cache. But this
    must still degrade gracefully rather than raise, for corrupt input."""
    mock_pdfium.PdfDocument.side_effect = RuntimeError("corrupt PDF")
    assert await OllamaVisionExtractor().render_first_page(PDF_BYTES) is None


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.pdfium", None)
async def test_render_first_page_returns_none_without_pdfium():
    assert await OllamaVisionExtractor().render_first_page(PDF_BYTES) is None


def _fake_ollama_response(text: str):
    """A context-manager stand-in for `urllib.request.urlopen`'s return value,
    matching the shape every OllamaVisionExtractor test in this file mocks."""
    import json as _json

    class _Resp:
        def read(self_inner):
            return _json.dumps({"response": text}).encode()

        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *args):
            return False

    return _Resp()


# ==========================================
# Header-band repair (crop-and-escalate)
#
# No trigger signal gates this -- calibrating one (header symbol-noise
# density) against the real 45-document scanned corpus this project ships
# (datasets/resmi_yazisma/00_gelen_kaynaklar/cevap_yazisi/) found none that
# discriminates (Pearson r=0.036 with known parser gaps controlled for), so
# it runs unconditionally on every OCR result instead. See HEADER_BAND_FRACTION
# and FallbackDocumentExtractor._maybe_repair_header for the full rationale.
# ==========================================
@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.urllib.request.urlopen")
async def test_transcribe_header_band_crops_only_the_top_fraction(mock_urlopen):
    mock_urlopen.return_value = _fake_ollama_response("T.C.\nÖRNEK BAKANLIĞI")
    page = Image.new("L", (1000, 2000), color=255)

    with patch.object(Image.Image, "crop", wraps=page.crop) as mock_crop:
        result = await OllamaVisionExtractor().transcribe_header_band(page)

    assert result == "T.C.\nÖRNEK BAKANLIĞI"
    # HEADER_BAND_FRACTION default (0.28) of a 2000px-tall page.
    mock_crop.assert_called_once_with((0, 0, 1000, 560))


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.urllib.request.urlopen")
async def test_transcribe_header_band_wraps_a_failed_call(mock_urlopen):
    mock_urlopen.side_effect = OSError("connection refused")
    page = Image.new("L", (100, 400), color=255)

    with pytest.raises(DocumentExtractionError):
        await OllamaVisionExtractor().transcribe_header_band(page)


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.urllib.request.urlopen")
async def test_header_repair_splices_the_transcription_over_the_first_page(mock_urlopen):
    mock_urlopen.return_value = _fake_ollama_response("T.C.\nÖRNEK BAKANLIĞI (onarıldı)")
    vision = OllamaVisionExtractor()
    chain = FallbackDocumentExtractor([], header_repair=vision)
    original_lines = [f"satır {i}" for i in range(20)]  # > HEADER_REPAIR_LINE_COUNT (14)
    result = ExtractedDocument(
        text="\n".join(original_lines),
        pages=["\n".join(original_lines)],
        page_count=1,
        extractor="tesseract",
        used_ocr=True,
    )
    raster_cache = {vision.dpi: [Image.new("L", (100, 400), color=255)]}

    repaired = await chain._maybe_repair_header(result, raster_cache, PDF_BYTES, {})

    assert repaired.pages[0].startswith("T.C.\nÖRNEK BAKANLIĞI (onarıldı)\n")
    # The body past the header-line count survives untouched.
    assert "satır 14" in repaired.pages[0]
    assert "satır 19" in repaired.pages[0]
    assert "satır 5" not in repaired.pages[0]  # was inside the replaced header band


@pytest.mark.asyncio
async def test_header_repair_is_skipped_for_born_digital_text():
    """used_ocr=False and no scan-text-layer signal -- an ordinary
    born-digital PDF (real vector/text content, no full-page scan image)
    must never pay the repair cost."""
    chain = FallbackDocumentExtractor(
        [],
        header_repair=OllamaVisionExtractor(),
        scan_text_layer_probe=lambda content: False,
    )
    result = ExtractedDocument(
        text="x", pages=["x"], page_count=1, extractor="opendataloader", used_ocr=False
    )

    repaired = await chain._maybe_repair_header(result, {}, PDF_BYTES, {})

    assert repaired is result


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.urllib.request.urlopen")
async def test_header_repair_runs_for_a_class_a_scan_text_layer(mock_urlopen):
    """used_ocr=False but scan_text_layer_probe reports scanner-origin junk
    text (Class A, e.g. real CY-034/CY-050) -- repair must still run despite
    the flag, since OpenDataLoader/Pdfium read this exactly like a genuine
    text layer even though it is exactly as corrupted as real OCR output."""
    mock_urlopen.return_value = _fake_ollama_response("T.C.\nÖRNEK BAKANLIĞI (onarıldı)")
    vision = OllamaVisionExtractor()
    chain = FallbackDocumentExtractor(
        [], header_repair=vision, scan_text_layer_probe=lambda content: True
    )
    original_lines = [f"satır {i}" for i in range(20)]
    result = ExtractedDocument(
        text="\n".join(original_lines),
        pages=["\n".join(original_lines)],
        page_count=1,
        extractor="opendataloader",
        used_ocr=False,
    )
    raster_cache = {vision.dpi: [Image.new("L", (100, 400), color=255)]}

    repaired = await chain._maybe_repair_header(result, raster_cache, PDF_BYTES, {})

    assert repaired.pages[0].startswith("T.C.\nÖRNEK BAKANLIĞI (onarıldı)\n")


@pytest.mark.asyncio
async def test_header_repair_is_skipped_when_no_repair_extractor_is_configured():
    chain = FallbackDocumentExtractor([], header_repair=None)
    result = ExtractedDocument(
        text="x", pages=["x"], page_count=1, extractor="tesseract", used_ocr=True
    )

    repaired = await chain._maybe_repair_header(result, {}, PDF_BYTES, {})

    assert repaired is result


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.urllib.request.urlopen")
async def test_header_repair_self_rasterises_page_one_when_never_rendered(mock_urlopen):
    """Class A never rasterises on its own -- OpenDataLoader/Pdfium read the
    text layer directly and render nothing -- so raster_cache being empty
    must not mean 'skip'; repair renders page 1 itself instead."""
    mock_urlopen.return_value = _fake_ollama_response("T.C.\nÖRNEK BAKANLIĞI (onarıldı)")
    vision = OllamaVisionExtractor()
    chain = FallbackDocumentExtractor(
        [], header_repair=vision, scan_text_layer_probe=lambda content: True
    )
    original_lines = [f"satır {i}" for i in range(20)]
    result = ExtractedDocument(
        text="\n".join(original_lines),
        pages=["\n".join(original_lines)],
        page_count=1,
        extractor="opendataloader",
        used_ocr=False,
    )
    rendered_page = Image.new("L", (100, 400), color=255)

    with patch.object(
        vision, "render_first_page", new=AsyncMock(return_value=rendered_page)
    ) as mock_render:
        repaired = await chain._maybe_repair_header(result, {}, PDF_BYTES, {})

    mock_render.assert_called_once_with(PDF_BYTES)
    assert repaired.pages[0].startswith("T.C.\nÖRNEK BAKANLIĞI (onarıldı)\n")


@pytest.mark.asyncio
async def test_header_repair_is_skipped_when_page_one_cannot_be_rendered():
    """Rasterisation itself failing (corrupt content, no pages) must degrade
    to the original text, not raise."""
    vision = OllamaVisionExtractor()
    chain = FallbackDocumentExtractor(
        [], header_repair=vision, scan_text_layer_probe=lambda content: True
    )
    result = ExtractedDocument(
        text="x", pages=["x"], page_count=1, extractor="opendataloader", used_ocr=False
    )

    with patch.object(vision, "render_first_page", new=AsyncMock(return_value=None)):
        repaired = await chain._maybe_repair_header(result, {}, PDF_BYTES, {})

    assert repaired is result


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.urllib.request.urlopen")
async def test_header_repair_never_writes_the_self_rendered_page_into_raster_cache(
    mock_urlopen,
):
    """A partial, page-1-only entry in raster_cache would make a later
    full-document OCR pass silently transcribe only page 1 and drop the
    rest of the document -- the self-rendered page must stay local to this
    repair call."""
    mock_urlopen.return_value = _fake_ollama_response("T.C.\nÖRNEK BAKANLIĞI (onarıldı)")
    vision = OllamaVisionExtractor()
    chain = FallbackDocumentExtractor(
        [], header_repair=vision, scan_text_layer_probe=lambda content: True
    )
    result = ExtractedDocument(
        text="x", pages=["x"], page_count=1, extractor="opendataloader", used_ocr=False
    )
    raster_cache: dict = {}

    with patch.object(
        vision,
        "render_first_page",
        new=AsyncMock(return_value=Image.new("L", (10, 10))),
    ):
        await chain._maybe_repair_header(result, raster_cache, PDF_BYTES, {})

    assert vision.dpi not in raster_cache


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.urllib.request.urlopen")
async def test_header_repair_degrades_to_the_original_text_on_a_failed_vision_call(mock_urlopen):
    """Must never turn a working extraction into a failed one."""
    mock_urlopen.side_effect = OSError("connection refused")
    vision = OllamaVisionExtractor()
    chain = FallbackDocumentExtractor([], header_repair=vision)
    result = ExtractedDocument(
        text="orijinal metin", pages=["orijinal metin"], page_count=1,
        extractor="tesseract", used_ocr=True,
    )
    raster_cache = {vision.dpi: [Image.new("L", (100, 400), color=255)]}

    repaired = await chain._maybe_repair_header(result, raster_cache, PDF_BYTES, {})

    assert repaired.text == "orijinal metin"


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.urllib.request.urlopen")
async def test_header_repair_degrades_to_the_original_text_on_an_empty_transcription(mock_urlopen):
    mock_urlopen.return_value = _fake_ollama_response("   ")
    vision = OllamaVisionExtractor()
    chain = FallbackDocumentExtractor([], header_repair=vision)
    result = ExtractedDocument(
        text="orijinal metin", pages=["orijinal metin"], page_count=1,
        extractor="tesseract", used_ocr=True,
    )
    raster_cache = {vision.dpi: [Image.new("L", (100, 400), color=255)]}

    repaired = await chain._maybe_repair_header(result, raster_cache, PDF_BYTES, {})

    assert repaired.text == "orijinal metin"


# ------------------------------------------------------------------------
# Field-triggered escalation, combined with header repair inside the chain
# loop -- these exercise the two traps repairing a candidate mid-loop
# introduces (see fallback.py's own comments on `repair_cache` and
# `best_repaired`).
# ------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.urllib.request.urlopen")
async def test_repair_crop_is_transcribed_once_per_extract_call(mock_urlopen):
    """Page 1's crop is identical for every candidate within one extract()
    call (same image, same model, temperature 0) -- transcribing it once
    and reusing the text avoids paying the vision-model cost again for every
    candidate that gets rejected on header-field count."""
    mock_urlopen.return_value = _fake_ollama_response("T.C.\nÖRNEK BAKANLIĞI (onarıldı)")
    vision = OllamaVisionExtractor()
    # No space before the digit: "satırN" is one token to quality_ratio's
    # tokeniser (letters+digits share a token class), so every line reads as
    # a "real word" and quality_ratio is comfortably >= the 0.6 default --
    # unlike "satır N", which splits into two tokens per line and scores
    # only 0.5, silently failing `_is_acceptable` and never actually
    # reaching the in-loop repair path this test means to exercise.
    text = "\n".join(f"satır{i}" for i in range(20))
    first = _FakeExtractor("first", text=text, used_ocr=True)
    second = _FakeExtractor("second", text=text, used_ocr=True)
    chain = FallbackDocumentExtractor(
        [first, second],
        min_char_count=10,
        header_repair=vision,
        header_field_probe=lambda page: 0,  # noqa: E731 -- never enough, both escalate
        min_header_field_count=1,
    )
    raster_cache = {vision.dpi: [Image.new("L", (100, 400), color=255)]}

    await chain.extract(b"data", raster_cache=raster_cache)

    assert first.call_count == 1
    assert second.call_count == 1
    assert mock_urlopen.call_count == 1


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.urllib.request.urlopen")
async def test_best_effort_does_not_double_splice_an_already_repaired_result(mock_urlopen):
    """The loop-exit best-effort return must not repair a `best` that was
    already repaired inside the loop. Splicing twice would re-replace the
    first HEADER_REPAIR_LINE_COUNT (14) lines of what is by then the
    repaired header (1 line) plus real body lines -- on a 7-line repaired
    page that deletes the body entirely."""
    mock_urlopen.return_value = _fake_ollama_response("T.C.\nÖRNEK BAKANLIĞI (onarıldı)")
    vision = OllamaVisionExtractor()
    text = "\n".join(f"satır{i}" for i in range(20))  # see quality_ratio note above
    only = _FakeExtractor("only", text=text, used_ocr=True)
    chain = FallbackDocumentExtractor(
        [only],
        min_char_count=10,
        header_repair=vision,
        header_field_probe=lambda page: 0,  # noqa: E731 -- forces best-effort return
        min_header_field_count=1,
    )
    raster_cache = {vision.dpi: [Image.new("L", (100, 400), color=255)]}

    result = await chain.extract(b"data", raster_cache=raster_cache)

    assert result.pages[0].startswith("T.C.\nÖRNEK BAKANLIĞI (onarıldı)\n")
    assert "satır14" in result.pages[0]
    assert "satır19" in result.pages[0]


@pytest.mark.asyncio
async def test_max_ocr_pages_skips_full_page_vision_but_not_header_repair():
    """A long attachment bundle should not pay full-document vision cost to
    fix header fields that only ever live on page 1: the vision extractor
    (also configured as `header_repair`) is skipped as a *chain member* once
    a prior candidate's page count exceeds MAX_OCR_PAGES, but header-band
    repair -- always page-1-only regardless of document length -- still
    applies to whichever result the chain does return."""
    with patch("app.infrastructure.extractors.vision.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _fake_ollama_response("T.C.\nÖRNEK BAKANLIĞI (onarıldı)")
        vision = OllamaVisionExtractor()

        class _LongDocument(_FakeExtractor):
            async def extract(self, content, *, file_name=None, mime_type=None, raster_cache=None):
                result = await super().extract(
                    content, file_name=file_name, mime_type=mime_type, raster_cache=raster_cache
                )
                return result.model_copy(update={"page_count": MAX_OCR_PAGES + 5})

        text = "\n".join(f"satır{i}" for i in range(20))  # see quality_ratio note above
        long_doc = _LongDocument("long_doc", text=text, used_ocr=True)
        chain = FallbackDocumentExtractor(
            [long_doc, vision],
            min_char_count=10,
            header_repair=vision,
            header_field_probe=lambda page: 0,  # noqa: E731 -- long_doc always escalates
            min_header_field_count=1,
        )
        raster_cache = {vision.dpi: [Image.new("L", (100, 400), color=255)]}

        result = await chain.extract(b"data", raster_cache=raster_cache)

    # The vision extractor never ran as a full chain member (its own
    # .extract() would have produced text="T.C.\nÖRNEK BAKANLIĞI (onarıldı)"
    # with no "satır" lines at all) -- long_doc's best-effort result won
    # instead, with header repair still spliced over its first page.
    assert result.extractor == "long_doc"
    assert result.pages[0].startswith("T.C.\nÖRNEK BAKANLIĞI (onarıldı)\n")
    assert "satır19" in result.pages[0]


# ==========================================
# get_document_extractor -- process-wide chain wiring
# ==========================================
@pytest.fixture
def _reset_document_extractor_singleton():
    """`get_document_extractor` caches its chain in a module global, built
    once per process -- reset it around each test so one test's chain never
    leaks into the next."""
    import app.infrastructure.extractors as extractors_module

    extractors_module._document_extractor = None
    yield
    extractors_module._document_extractor = None


def test_get_document_extractor_wires_a_header_field_probe(
    _reset_document_extractor_singleton,
):
    from app.infrastructure.extractors import get_document_extractor

    chain = get_document_extractor()

    assert chain.header_field_probe is not None
    assert chain.header_field_probe("Sayı : E-123\nKonu : Test") >= 1


def test_get_document_extractor_wires_a_scan_text_layer_probe(
    _reset_document_extractor_singleton,
):
    from app.infrastructure.extractors import get_document_extractor

    chain = get_document_extractor()

    assert chain.scan_text_layer_probe is not None
    # Wired to the real is_scanned_text_layer -- garbage bytes must fail
    # closed (False), not raise.
    assert chain.scan_text_layer_probe(b"not a pdf") is False


def test_get_document_extractor_returns_the_same_instance_across_calls(
    _reset_document_extractor_singleton,
):
    from app.infrastructure.extractors import get_document_extractor

    first = get_document_extractor()
    second = get_document_extractor()

    assert first is second


# ==========================================
# detected_marks wiring (real images, nothing about PIL/numpy mocked --
# geometry must be genuine; only the OCR/model calls themselves are faked)
# ==========================================
def _png_bytes_with_a_stamp_shaped_block() -> bytes:
    page = Image.new("L", (800, 1000), color=255)
    draw = ImageDraw.Draw(page)
    # 200x200, above marks._STAMP_MIN_DIMENSION_PX. A textured ring, not a
    # solid fill -- marks._classify requires a real seal's detailed-artwork
    # run density (see marks._STAMP_MIN_RUN_DENSITY), which a flat fill does
    # not have (a flat fill's run density matches a genuine signature's, not
    # a stamp's -- that collision is exactly the bug this module's own
    # ground-truth calibration found and fixed).
    draw.ellipse([550, 750, 750, 950], outline=0, width=10)
    draw.ellipse([580, 780, 720, 920], outline=0, width=6)
    for x in range(550, 750, 14):
        draw.line([(x, 820), (x, 880)], fill=0, width=4)
    buffer = io.BytesIO()
    page.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.tesseract.pytesseract")
async def test_tesseract_extractor_populates_detected_marks(mock_pytesseract):
    mock_pytesseract.image_to_string.return_value = "taranmis metin"

    result = await TesseractExtractor().extract(
        _png_bytes_with_a_stamp_shaped_block(), mime_type="image/png"
    )

    assert any(m.kind == "stamp" and m.page == 1 for m in result.detected_marks)


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.urllib.request.urlopen")
async def test_vision_extractor_populates_detected_marks_for_a_direct_image(mock_urlopen):
    mock_urlopen.return_value = _fake_ollama_response("bir metin")

    result = await OllamaVisionExtractor().extract(
        _png_bytes_with_a_stamp_shaped_block(), mime_type="image/png"
    )

    assert any(m.kind == "stamp" and m.page == 1 for m in result.detected_marks)


@pytest.mark.asyncio
async def test_a_malformed_direct_image_degrades_detected_marks_without_failing_transcription():
    """Mark detection decodes the image separately from transcription (see
    OllamaVisionExtractor.extract) specifically so a decode failure here
    cannot break a transcription that would otherwise have succeeded."""
    with patch(
        "app.infrastructure.extractors.vision.urllib.request.urlopen",
        return_value=_fake_ollama_response("bir metin"),
    ):
        result = await OllamaVisionExtractor().extract(b"not a real image", mime_type="image/png")

    assert result.text == "bir metin"
    assert result.detected_marks == []


@pytest.mark.asyncio
@patch("app.infrastructure.extractors.vision.urllib.request.urlopen")
async def test_extract_applies_header_repair_to_an_early_accepted_result(mock_urlopen):
    """Integration: the accept-early return path (`_is_acceptable` passes)
    must also go through header repair, not only the best-effort fallback path."""
    mock_urlopen.return_value = _fake_ollama_response("Onarılmış başlık")
    vision = OllamaVisionExtractor()
    accepted = _FakeExtractor("tesseract", text="y" * 250)
    accepted_result = ExtractedDocument(
        text="y" * 250, pages=["y" * 250], page_count=1, extractor="tesseract", used_ocr=True
    )

    async def _extract(*args, **kwargs):
        kwargs["raster_cache"][vision.dpi] = [Image.new("L", (100, 400), color=255)]
        return accepted_result

    accepted.extract = _extract
    chain = FallbackDocumentExtractor([accepted], min_char_count=200, header_repair=vision)

    result = await chain.extract(b"data")

    assert result.pages[0].startswith("Onarılmış başlık")
