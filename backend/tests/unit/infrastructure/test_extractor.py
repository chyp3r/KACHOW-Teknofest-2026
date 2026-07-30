"""Unit tests for the document text extraction chain."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
    has_pdf_magic_bytes,
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

    async def extract(self, content, *, file_name=None, mime_type=None):
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
