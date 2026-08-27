"""Unit tests for app.domains.drafts.export (docx / pdf render)."""

import io
import zipfile

from app.domains.drafts.export import (
    FONT_SIZE_PT,
    draft_subject,
    filename_for,
    render_docx,
    render_pdf,
)

TURKISH = (
    "İçişleri Bakanlığına\n\n"
    "Sayın Yetkili, ğ ş ı İ ö ü ç Ğ Ş Ö Ü Ç harfleri korunmalı.\n\n"
    "Bilgilerinize arz ederim."
)


def test_draft_subject_reads_the_konu_line():
    assert draft_subject("Sayı: 1\nKonu: Yıllık izin\n\nGövde") == "Yıllık izin"
    assert draft_subject("Konu: [Konu]") is None
    assert draft_subject("başlıksız metin") is None


def test_filename_slug_transliterates_turkish():
    name = filename_for(
        subject="Yıllık İzin Talebi", correspondence_type=None, version=4, fmt="docx"
    )
    assert name == "yillik-izin-talebi-v4.docx"


def test_docx_uses_times_new_roman_12pt_and_keeps_turkish():
    payload = render_docx(TURKISH, subject="Türkçe testi", version=2)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        styles_xml = archive.read("word/styles.xml").decode("utf-8")
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "Times New Roman" in styles_xml
    # python-docx yarım punto birimiyle yazar: 12pt -> 24
    assert f'w:sz w:val="{FONT_SIZE_PT * 2}"' in styles_xml
    assert "İçişleri Bakanlığına" in document_xml
    assert "Ğ Ş Ö Ü Ç" in document_xml


def test_pdf_renders_turkish_characters_in_the_text_layer():
    payload = render_pdf(TURKISH, subject="Türkçe testi", version=1)
    assert payload[:5] == b"%PDF-"

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(io.BytesIO(payload))
    text = pdf.get_page(0).get_textpage().get_text_range()

    assert "İçişleri Bakanlığına" in text
    assert "Müşavirliği" not in text  # bu belgede hedef birim verilmedi
    assert "ğ ş ı İ ö ü ç" in text
