"""Bir taslak versiyonunu indirilebilir bir belgeye (docx / pdf) dönüştürür.

`drafts.content` düz metindir -- writer prompt'unun ürettiği resmî yazı, satır
satır. Buradaki iki render fonksiyonu o metni *olduğu gibi* taşır (her satır bir
paragraf); amaç sadık bir kopya, yeniden biçimlendirme değil. Router
(`GET /drafts/{id}/export`) bunları çağırıp byte'ları bir `attachment` olarak
döndürür.

`python-docx` ve `reportlab` `requirements.txt` içindedir (bkz. oradaki not).
"""

from __future__ import annotations

import io
import re
import unicodedata
from typing import Optional

_KONU_LINE = re.compile(r"^[ \t]*Konu[ \t]*:[ \t]*(.+)$", re.IGNORECASE | re.MULTILINE)


def draft_subject(content: str) -> Optional[str]:
    """Taslağın kendi "Konu: ..." satırı, yoksa / doldurulmamış yer tutucuysa None.

    Frontend'deki ``draftSubject`` (``pages/draftTitle.ts``) ile aynı kural --
    dosya adını burada da aynı şekilde türetebilmek için.
    """
    match = _KONU_LINE.search(content or "")
    subject = (match.group(1).strip() if match else "") or ""
    if not subject or re.fullmatch(r"\[.+\]", subject):
        return None
    return subject


#: Türkçe harfler NFKD ile ASCII'ye ayrışmaz (ör. "ı" -> düşürülür, "Yıllık"
#: -> "Yllk"), bu yüzden önce elle çevrilir.
_TR_ASCII = str.maketrans(
    {
        "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
        "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
    }
)


def _slugify(value: str) -> str:
    """Bir başlığı dosya-güvenli bir ASCII slug'a indirger."""
    folded = value.translate(_TR_ASCII)
    folded = unicodedata.normalize("NFKD", folded).encode("ascii", "ignore").decode()
    folded = re.sub(r"[^A-Za-z0-9]+", "-", folded).strip("-").lower()
    return folded or "taslak"


def filename_for(
    *,
    subject: Optional[str],
    correspondence_type: Optional[str],
    version: int,
    fmt: str,
) -> str:
    """İndirilecek dosyanın adı: ``<konu-veya-tür>-v<n>.<fmt>`` (ASCII slug).

    ``Content-Disposition`` başlığı için; router ayrıca Türkçe karakterli özgün
    adı ``filename*`` (RFC 5987) ile taşır.
    """
    base = subject or (correspondence_type or "").replace("_", " ").strip() or "taslak"
    return f"{_slugify(base)}-v{version}.{fmt}"


def _meta_lines(
    *,
    subject: Optional[str],
    correspondence_type: Optional[str],
    destination: Optional[str],
    version: int,
) -> list[str]:
    """Belgenin en üstüne konan kısa künye (taslak metninin bir parçası değil)."""
    lines = ["TASLAK"]
    if subject:
        lines.append(f"Konu: {subject}")
    if correspondence_type:
        lines.append(f"Yazışma türü: {correspondence_type.replace('_', ' ')}")
    if destination:
        lines.append(f"Hedef birim: {destination}")
    lines.append(f"Sürüm: v{version}")
    return lines


def render_docx(
    content: str,
    *,
    subject: Optional[str] = None,
    correspondence_type: Optional[str] = None,
    destination: Optional[str] = None,
    version: int = 1,
) -> bytes:
    """Taslağı bir ``.docx`` byte dizisine dönüştürür."""
    from docx import Document
    from docx.shared import Pt

    document = Document()

    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    meta = _meta_lines(
        subject=subject,
        correspondence_type=correspondence_type,
        destination=destination,
        version=version,
    )
    heading = document.add_paragraph()
    run = heading.add_run(meta[0])
    run.bold = True
    run.font.size = Pt(13)
    for line in meta[1:]:
        para = document.add_paragraph(line)
        para.runs[0].font.size = Pt(9)
        para.runs[0].italic = True

    document.add_paragraph()  # künye ile gövde arasında boşluk

    for line in (content or "").split("\n"):
        # Boş satır da bir paragraf olarak korunur; resmî yazının kendi
        # aralıkları taslakta anlamlıdır.
        document.add_paragraph(line)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def render_pdf(
    content: str,
    *,
    subject: Optional[str] = None,
    correspondence_type: Optional[str] = None,
    destination: Optional[str] = None,
    version: int = 1,
) -> bytes:
    """Taslağı bir ``.pdf`` byte dizisine dönüştürür."""
    from xml.sax.saxutils import escape

    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
        title=subject or "Taslak",
    )

    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "DraftBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=15,
        alignment=TA_LEFT,
    )
    meta_style = ParagraphStyle(
        "DraftMeta",
        parent=body_style,
        fontSize=9,
        textColor=HexColor("#555555"),
    )
    title_style = ParagraphStyle(
        "DraftTitle", parent=body_style, fontSize=13, spaceAfter=6, leading=16
    )

    meta = _meta_lines(
        subject=subject,
        correspondence_type=correspondence_type,
        destination=destination,
        version=version,
    )
    flow: list = [Paragraph(f"<b>{escape(meta[0])}</b>", title_style)]
    for line in meta[1:]:
        flow.append(Paragraph(f"<i>{escape(line)}</i>", meta_style))
    flow.append(Spacer(1, 0.6 * cm))

    for line in (content or "").split("\n"):
        if line.strip():
            flow.append(Paragraph(escape(line), body_style))
        else:
            flow.append(Spacer(1, 0.35 * cm))

    doc.build(flow)
    return buffer.getvalue()
