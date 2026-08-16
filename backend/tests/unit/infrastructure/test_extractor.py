"""Unit tests for the document text extraction chain."""

import io
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document
from PIL import Image, ImageDraw  # real Pillow, not mocked: crop/mark geometry must be genuine

from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
    has_pdf_magic_bytes,
    has_pdf_text_layer,
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

    def __init__(self, name, text="", error=None, supported=True):
        self.name = name
        self._text = text
        self._error = error
        self._supported = supported
        self.call_count = 0

    async def extract(self, content, *, file_name=None, mime_type=None, raster_cache=None):
        self.call_count += 1
        if self._error is not None:
            raise self._error
        return ExtractedDocument(
            text=self._text, pages=[self._text], page_count=1, extractor=self.name
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

    repaired = await chain._maybe_repair_header(result, raster_cache)

    assert repaired.pages[0].startswith("T.C.\nÖRNEK BAKANLIĞI (onarıldı)\n")
    # The body past the header-line count survives untouched.
    assert "satır 14" in repaired.pages[0]
    assert "satır 19" in repaired.pages[0]
    assert "satır 5" not in repaired.pages[0]  # was inside the replaced header band


@pytest.mark.asyncio
async def test_header_repair_is_skipped_when_the_result_is_not_ocr():
    chain = FallbackDocumentExtractor([], header_repair=OllamaVisionExtractor())
    result = ExtractedDocument(
        text="x", pages=["x"], page_count=1, extractor="pdfium", used_ocr=False
    )

    repaired = await chain._maybe_repair_header(result, {})

    assert repaired is result


@pytest.mark.asyncio
async def test_header_repair_is_skipped_when_no_repair_extractor_is_configured():
    chain = FallbackDocumentExtractor([], header_repair=None)
    result = ExtractedDocument(
        text="x", pages=["x"], page_count=1, extractor="tesseract", used_ocr=True
    )

    repaired = await chain._maybe_repair_header(result, {})

    assert repaired is result


@pytest.mark.asyncio
async def test_header_repair_is_skipped_when_the_page_was_never_rasterised():
    """The vision extractor's own DPI has no entry in raster_cache -- e.g. the
    result came from a non-PDF image path that never populated it."""
    vision = OllamaVisionExtractor()
    chain = FallbackDocumentExtractor([], header_repair=vision)
    result = ExtractedDocument(
        text="x", pages=["x"], page_count=1, extractor="tesseract", used_ocr=True
    )

    repaired = await chain._maybe_repair_header(result, {})

    assert repaired is result


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

    repaired = await chain._maybe_repair_header(result, raster_cache)

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

    repaired = await chain._maybe_repair_header(result, raster_cache)

    assert repaired.text == "orijinal metin"


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
