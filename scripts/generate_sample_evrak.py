"""Render the synthetic evrak dataset to PDF.

Reads every `datasets/sample/evrak_*.txt` and writes a matching `.pdf`. Samples
whose ground truth sets `"scanned": true` are additionally rasterised so the PDF
carries no text layer, which forces the OCR path in the extraction chain.

Usage:
    python scripts/generate_sample_evrak.py

Requires the dev dependencies (`pip install -r backend/requirements-dev.txt`).
"""

import glob
import io
import json
import os
import sys

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

SAMPLE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "datasets", "sample"
)

# ReportLab's built-in Type1 fonts use WinAnsi encoding, which lacks ş, ğ, ı and İ
# -- Turkish text silently renders as blanks. A Unicode TTF must be registered.
FONT_NAME = "EvrakUnicode"
FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
)

FONT_SIZE = 11
LINE_HEIGHT = 20
LEFT_MARGIN = 70
TOP_MARGIN = 780
OCR_RENDER_SCALE = 300 / 72


def register_font() -> None:
    """Register the first available Unicode TTF.

    Raises:
        SystemExit: If no candidate font is present, since silently rendering
            Turkish characters as blanks would corrupt the whole dataset.
    """
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            pdfmetrics.registerFont(TTFont(FONT_NAME, path))
            print(f"Yazı tipi: {path}")
            return
    sys.exit(
        "HATA: Unicode TTF bulunamadı. Türkçe karakterler boş görünecekti.\n"
        "Denenen yollar:\n  " + "\n  ".join(FONT_CANDIDATES)
    )


def render_pdf(lines: list[str]) -> bytes:
    """Render text lines onto a single A4 page.

    Args:
        lines: Text lines in document order.

    Returns:
        The PDF bytes.
    """
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setFont(FONT_NAME, FONT_SIZE)
    y = TOP_MARGIN
    for line in lines:
        pdf.drawString(LEFT_MARGIN, y, line)
        y -= LINE_HEIGHT
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def rasterize(pdf_bytes: bytes) -> bytes:
    """Convert a PDF into an image-only PDF with no text layer.

    Args:
        pdf_bytes: A born-digital PDF.

    Returns:
        PDF bytes whose pages are raster images, forcing OCR on extraction.
    """
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        image = document[0].render(scale=OCR_RENDER_SCALE).to_pil()
    finally:
        document.close()

    buffer = io.BytesIO()
    width, height = A4
    pdf = canvas.Canvas(buffer, pagesize=A4)
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)
    from reportlab.lib.utils import ImageReader

    pdf.drawImage(ImageReader(image_buffer), 0, 0, width=width, height=height)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def main() -> int:
    register_font()
    text_paths = sorted(glob.glob(os.path.join(SAMPLE_DIR, "evrak_*.txt")))
    if not text_paths:
        sys.exit(f"HATA: {SAMPLE_DIR} içinde evrak_*.txt bulunamadı.")

    generated = 0
    for text_path in text_paths:
        base = os.path.splitext(text_path)[0]
        with open(text_path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()

        scanned = False
        ground_truth_path = f"{base}.json"
        if os.path.isfile(ground_truth_path):
            with open(ground_truth_path, encoding="utf-8") as handle:
                scanned = json.load(handle).get("scanned", False)

        pdf_bytes = render_pdf(lines)
        if scanned:
            pdf_bytes = rasterize(pdf_bytes)

        with open(f"{base}.pdf", "wb") as handle:
            handle.write(pdf_bytes)

        kind = "taranmış görüntü" if scanned else "metin katmanlı"
        print(
            f"  {os.path.basename(base)}.pdf  "
            f"({len(pdf_bytes) // 1024} KB, {kind})"
        )
        generated += 1

    print(f"\nTamamlandı: {generated} PDF üretildi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
