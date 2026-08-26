import asyncio
import logging
from typing import Optional

from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
    has_pdf_magic_bytes,
    has_pdf_text_layer,
    matches_extension,
)

logger = logging.getLogger(__name__)

try:  # pragma: no cover - testlerde patch ile çalıştırılır
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None

PDF_EXTENSIONS = {"pdf"}


class PdfiumExtractor(BaseDocumentExtractor):
    """`pypdfium2` üzerine kurulu saf Python PDF metin çıkarıcı.

    `OpenDataLoaderExtractor`'ın arkasında Java gerektirmeyen güvenlik ağı
    olarak görev yapar: byte'ları geçici dosya ve JVM olmadan doğrudan okur,
    böylece Java runtime'ı yoksa veya başlaması yavaşsa boru hattı çalışmaya
    devam eder. Okuma sırası onarımı veya tablo yapısı olmadan yalnızca ham
    metin akışını kurtarır.
    """

    name = "pdfium"

    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        raster_cache: Optional[dict] = None,
    ) -> ExtractedDocument:
        """Bir PDF'in gömülü metin katmanını çıkar.

        Args:
            content: Ham PDF byte'ları.
            file_name: Orijinal dosya adı (kullanılmıyor).
            mime_type: Bildirilen içerik türü (kullanılmıyor).
            raster_cache: Kullanılmıyor; bu çıkarıcı PDF'in kendi metin
                katmanını okur ve hiçbir şeyi rasterize etmez.

        Returns:
            Sayfa başına bir girdi olan çıkarılan metin.

        Raises:
            DocumentExtractionError: pypdfium2 kullanılamıyorsa veya ayrıştırma başarısız olursa.
        """
        if pdfium is None:
            raise DocumentExtractionError(
                "pypdfium2 kurulu değil; PDF metin katmanı okunamadı."
            )

        try:
            pages = await asyncio.to_thread(self._read_pages, content)
        except Exception as exc:
            raise DocumentExtractionError(
                f"PDFium ile PDF okunamadı: {exc}"
            ) from exc

        text = "\n\n".join(pages).strip()
        logger.info(
            "PdfiumExtractor read %d page(s), %d characters.", len(pages), len(text)
        )
        return ExtractedDocument(
            text=text,
            pages=pages,
            page_count=len(pages),
            extractor=self.name,
            used_ocr=False,
        )

    def _read_pages(self, content: bytes) -> list[str]:
        """Her sayfanın metin katmanını oku.

        Args:
            content: Ham PDF byte'ları.

        Returns:
            Belge sırasına göre sayfa metni.
        """
        document = pdfium.PdfDocument(content)
        try:
            pages = []
            for page in document:
                text_page = page.get_textpage()
                try:
                    pages.append(text_page.get_text_range())
                finally:
                    text_page.close()
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
        """Metin katmanı olan PDF'leri kabul et; gerçek taramaları doğrudan reddet.

        Bu çıkarıcı `has_pdf_text_layer`'ın zaten sonda ettiği metin
        katmanını tam olarak okur -- gerçek bir taramada `_read_pages` zaten
        hiçbir şey döndürmeyecektir, bu yüzden burada atlamak bir PDF
        aç-ve-yinele geçişinden tasarruf sağlar ve zincirin OCR
        çıkarıcılarına daha erken ulaşmasını sağlar.
        """
        is_pdf = (
            has_pdf_magic_bytes(content)
            or mime_type == "application/pdf"
            or matches_extension(file_name, PDF_EXTENSIONS)
        )
        return is_pdf and has_pdf_text_layer(content)
