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
    """Decodes already-textual uploads without invoking a document parser."""

    name = "plain_text"

    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        raster_cache: Optional[dict] = None,
    ) -> ExtractedDocument:
        """Decode the bytes as UTF-8, replacing undecodable sequences.

        Args:
            content: The raw document bytes.
            file_name: Original file name (unused).
            mime_type: Declared content type (unused).
            raster_cache: Unused; this extractor never rasterises anything.

        Returns:
            The decoded text as a single page.
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
        """Accept only declared text types or text extensions, never binary."""
        if has_pdf_magic_bytes(content):
            return False
        if mime_type and mime_type.startswith(TEXT_MIME_PREFIX):
            return True
        return matches_extension(file_name, TEXT_EXTENSIONS)
