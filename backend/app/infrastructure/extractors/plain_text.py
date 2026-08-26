import logging
from typing import Optional

from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    ExtractedDocument,
    has_pdf_magic_bytes,
    matches_extension,
)

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = {"txt", "md", "csv"}
TEXT_MIME_PREFIX = "text/"


class PlainTextExtractor(BaseDocumentExtractor):
    """Halihazırda metinsel yüklemeleri bir belge ayrıştırıcı çağırmadan çözer."""

    name = "plain_text"

    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        raster_cache: Optional[dict] = None,
    ) -> ExtractedDocument:
        """Byte'ları, çözülemeyen dizileri değiştirerek UTF-8 olarak çöz.

        Args:
            content: Ham belge byte'ları.
            file_name: Orijinal dosya adı (kullanılmıyor).
            mime_type: Bildirilen içerik türü (kullanılmıyor).
            raster_cache: Kullanılmıyor; bu çıkarıcı hiçbir şeyi rasterize etmez.

        Returns:
            Tek sayfa olarak çözülen metin.
        """
        text = content.decode("utf-8", errors="replace")
        logger.info("PlainTextExtractor decoded %d characters.", len(text))
        return ExtractedDocument(
            text=text,
            pages=[text],
            page_count=1,
            extractor=self.name,
            used_ocr=False,
        )

    def supports(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> bool:
        """Yalnızca bildirilen metin türlerini veya metin uzantılarını kabul et, asla ikiliyi değil."""
        if has_pdf_magic_bytes(content):
            return False
        if mime_type and mime_type.startswith(TEXT_MIME_PREFIX):
            return True
        return matches_extension(file_name, TEXT_EXTENSIONS)
