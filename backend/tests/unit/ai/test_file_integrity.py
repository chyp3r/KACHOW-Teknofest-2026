"""Unit tests for magic-byte file validation and archive-bomb safeguards."""

import io
import zipfile

import pytest

from app.ai.guardrails import file_integrity
from app.ai.guardrails.file_integrity import check_file_integrity

#: A real, minimally valid PDF (one blank page). Generated once via
#: `pypdfium2.PdfDocument.new()` + `.save()` -- pypdfium2 must be able to
#: actually reopen this, not just see the right magic bytes.
PDF_BYTES = (
    b"%PDF-1.7\r\n%\xa1\xb3\xc5\xd7\r\n1 0 obj\r\n<</Pages 2 0 R /Type/Catalog>>\r\n"
    b"endobj\r\n2 0 obj\r\n<</Count 1/Kids[ 4 0 R ]/Type/Pages>>\r\nendobj\r\n"
    b"3 0 obj\r\n<</CreationDate(D:20260805100924+00'00')/Creator(PDFium)>>\r\n"
    b"endobj\r\n4 0 obj\r\n<</MediaBox[ 0 0 200 200]/Parent 2 0 R /Resources"
    b"<<>>/Rotate 0/Type/Page>>\r\nendobj\r\nxref\r\n0 5\r\n0000000000 65535 f\r\n"
    b"0000000017 00000 n\r\n0000000066 00000 n\r\n0000000122 00000 n\r\n"
    b"0000000199 00000 n\r\ntrailer\r\n<<\r\n/Root 1 0 R\r\n/Info 3 0 R\r\n"
    b"/Size 5/ID[<D5D2D6972A5C2FE28B08F59A22694073><D5D2D6972A5C2FE28B08F59A22694073>]"
    b">>\r\nstartxref\r\n292\r\n%%EOF\r\n"
)

#: A real, minimally valid 10x10 PNG. Generated once via
#: `PIL.Image.new(...).save(buf, format="PNG")`.
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\n\x00\x00\x00\n\x08\x02"
    b"\x00\x00\x00\x02PX\xea\x00\x00\x00\x15IDATx\x9cc\xfc\xff\xff?\x03n\xc0"
    b"\x84Gn\x04K\x03\x00\xa5\xe3\x03\x11}\x92\xa6j\x00\x00\x00\x00IEND\xaeB`\x82"
)

OLE2_DOC_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 500


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buf.getvalue()


# ==========================================
# PDF
# ==========================================
def test_a_real_pdf_with_pdf_extension_passes():
    result = check_file_integrity(PDF_BYTES, file_name="evrak.pdf")
    assert result.ok is True


def test_pdf_extension_with_no_pdf_signature_is_rejected():
    result = check_file_integrity(b"bu bir pdf degil", file_name="evrak.pdf")
    assert result.ok is False
    assert "PDF imzası" in result.reason


def test_pdf_signature_with_unparseable_content_is_rejected():
    """The extension-spoofing gap this module closes: right magic bytes,
    but the content is not a real PDF structure."""
    result = check_file_integrity(
        b"%PDF-1.4\r\n" + b"garbage not a real pdf body " * 20,
        file_name="evrak.pdf",
    )
    assert result.ok is False
    assert "ayrıştırılamadı" in result.reason


def test_pdf_page_count_over_the_ceiling_is_rejected(monkeypatch):
    monkeypatch.setattr(file_integrity, "MAX_PDF_PAGES", 0)
    result = check_file_integrity(PDF_BYTES, file_name="evrak.pdf")
    assert result.ok is False
    assert "sayfa sayısı" in result.reason


# ==========================================
# Images
# ==========================================
def test_a_real_png_with_png_extension_passes():
    result = check_file_integrity(PNG_BYTES, file_name="evrak.png")
    assert result.ok is True


def test_image_extension_with_no_image_signature_is_rejected():
    result = check_file_integrity(b"bu bir gorsel degil", file_name="evrak.png")
    assert result.ok is False
    assert "görsel imzası" in result.reason


def test_image_signature_with_unparseable_content_is_rejected():
    result = check_file_integrity(
        b"\x89PNG\r\n\x1a\n" + b"garbage" * 20, file_name="evrak.png"
    )
    assert result.ok is False
    assert "ayrıştırılamadı" in result.reason


def test_image_pixel_count_over_the_ceiling_is_rejected(monkeypatch):
    monkeypatch.setattr(file_integrity, "MAX_IMAGE_PIXELS", 1)
    result = check_file_integrity(PNG_BYTES, file_name="evrak.png")
    assert result.ok is False
    assert "piksel" in result.reason


# ==========================================
# .doc (OLE2, or a renamed zip-based Office format)
# ==========================================
def test_genuine_ole2_doc_passes():
    result = check_file_integrity(OLE2_DOC_BYTES, file_name="evrak.doc")
    assert result.ok is True


def test_a_renamed_docx_under_doc_extension_is_archive_checked_not_rejected():
    """.docx isn't in ALLOWED_DOCUMENT_EXTENSIONS at all, so the only way a
    zip-based Office file arrives is renamed to .doc -- tolerate the
    structure, but it still goes through the archive-bomb check."""
    result = check_file_integrity(
        _zip_bytes({"word/document.xml": b"<xml>hello</xml>"}), file_name="evrak.doc"
    )
    assert result.ok is True


def test_doc_extension_with_neither_signature_is_rejected():
    result = check_file_integrity(b"plain text pretending to be doc", file_name="evrak.doc")
    assert result.ok is False
    assert "belge imzası" in result.reason


# ==========================================
# Archive-bomb protection
# ==========================================
def test_too_many_archive_entries_is_rejected(monkeypatch):
    monkeypatch.setattr(file_integrity, "MAX_ARCHIVE_ENTRIES", 2)
    archive = _zip_bytes({f"file{i}.xml": b"data" for i in range(5)})
    result = check_file_integrity(archive, file_name="evrak.doc")
    assert result.ok is False
    assert "girdi sayısı" in result.reason


def test_oversized_uncompressed_payload_is_rejected(monkeypatch):
    monkeypatch.setattr(file_integrity, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 10)
    archive = _zip_bytes({"big.xml": b"x" * 1000})
    result = check_file_integrity(archive, file_name="evrak.doc")
    assert result.ok is False
    assert "açılmış boyutu" in result.reason


def test_suspicious_compression_ratio_is_rejected(monkeypatch):
    monkeypatch.setattr(file_integrity, "MAX_ARCHIVE_COMPRESSION_RATIO", 1)
    # Highly repetitive content compresses far more than a 1x ratio allows.
    archive = _zip_bytes({"repetitive.xml": b"A" * 10_000})
    result = check_file_integrity(archive, file_name="evrak.doc")
    assert result.ok is False
    assert "sıkıştırma oranı" in result.reason


def test_nested_archive_member_is_rejected():
    inner = _zip_bytes({"inner.xml": b"data"})
    outer = _zip_bytes({"nested.zip": inner})
    result = check_file_integrity(outer, file_name="evrak.doc")
    assert result.ok is False
    assert "iç içe" in result.reason


def test_corrupt_zip_is_rejected():
    result = check_file_integrity(b"PK\x03\x04" + b"not a real zip", file_name="evrak.doc")
    assert result.ok is False


# ==========================================
# .txt
# ==========================================
def test_plain_text_with_txt_extension_passes():
    result = check_file_integrity("Sayın Makam, arz ederim.".encode("utf-8"), file_name="evrak.txt")
    assert result.ok is True


def test_txt_extension_disguising_a_pdf_is_rejected():
    result = check_file_integrity(PDF_BYTES, file_name="evrak.txt")
    assert result.ok is False
    assert "ikili bir dosya imzası" in result.reason


def test_txt_extension_disguising_an_archive_is_rejected():
    result = check_file_integrity(_zip_bytes({"a.xml": b"x"}), file_name="evrak.txt")
    assert result.ok is False


# ==========================================
# Unhandled extensions
# ==========================================
def test_an_extension_outside_the_checked_set_passes_through():
    """Already gated by the allow-list check this runs alongside; nothing
    further for this module to validate."""
    result = check_file_integrity(b"anything", file_name="evrak.xyz")
    assert result.ok is True
