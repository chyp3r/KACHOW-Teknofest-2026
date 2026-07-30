import asyncio
import contextlib
import logging
import os
import tempfile
from typing import Iterator, Optional

from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
    has_pdf_magic_bytes,
    matches_extension,
)

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised via patching in tests
    from langchain_opendataloader_pdf import OpenDataLoaderPDFLoader
except ImportError:  # pragma: no cover
    OpenDataLoaderPDFLoader = None

PDF_EXTENSIONS = {"pdf"}


@contextlib.contextmanager
def _temporary_pdf_path(content: bytes) -> Iterator[str]:
    """Materialise PDF bytes on disk inside a scratch directory.

    OpenDataLoader wraps a Java CLI that requires a real file and may write
    sibling artefacts next to it. Keeping the input and any output inside one
    `TemporaryDirectory` makes cleanup a single operation with no bookkeeping.

    Args:
        content: The raw PDF bytes.

    Yields:
        Absolute path of the materialised PDF file.
    """
    with tempfile.TemporaryDirectory(prefix="odl_") as work_dir:
        pdf_path = os.path.join(work_dir, "input.pdf")
        with open(pdf_path, "wb") as handle:
            handle.write(content)
        yield pdf_path


class OpenDataLoaderExtractor(BaseDocumentExtractor):
    """Layout-aware PDF extractor backed by OpenDataLoader PDF (Apache-2.0).

    Preferred extractor for born-digital PDFs because it recovers reading order
    for multi-column layouts, preserves table structure and emits headings, all
    of which help locate the header block of an official document. Requires a
    Java 11+ runtime on PATH; when Java or the package is absent the chain falls
    through to the pure-Python extractors.
    """

    name = "opendataloader"

    def __init__(self, output_format: str = "markdown") -> None:
        """Initialise the extractor.

        Args:
            output_format: OpenDataLoader output format; "markdown" retains
                headings and tables, "text" yields a flat transcript.
        """
        self.output_format = output_format

    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> ExtractedDocument:
        """Parse a PDF into per-page text using OpenDataLoader.

        Args:
            content: The raw PDF bytes.
            file_name: Original file name (unused).
            mime_type: Declared content type (unused).

        Returns:
            The extracted text with one entry per page.

        Raises:
            DocumentExtractionError: If the package is unavailable or parsing fails.
        """
        if OpenDataLoaderPDFLoader is None:
            raise DocumentExtractionError(
                "OpenDataLoader PDF kütüphanesi kurulu değil; PDF metni çıkarılamadı."
            )

        try:
            pages = await asyncio.to_thread(self._load_pages, content)
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError(
                f"OpenDataLoader ile PDF okunamadı: {exc}"
            ) from exc

        text = "\n\n".join(pages).strip()
        logger.info(
            "OpenDataLoaderExtractor parsed %d page(s), %d characters.",
            len(pages),
            len(text),
        )
        return ExtractedDocument(
            text=text,
            pages=pages,
            page_count=len(pages),
            extractor=self.name,
            used_ocr=False,
        )

    def _load_pages(self, content: bytes) -> list[str]:
        """Run the blocking loader against a temporary file and collect page text.

        Args:
            content: The raw PDF bytes.

        Returns:
            Page text in document order.
        """
        with _temporary_pdf_path(content) as pdf_path:
            loader = OpenDataLoaderPDFLoader(
                file_path=pdf_path,
                format=self.output_format,
                split_pages=True,
                quiet=True,
            )
            documents = loader.load()
        return [document.page_content for document in documents]

    def supports(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> bool:
        """Accept PDFs only, detected by signature or declared type."""
        if has_pdf_magic_bytes(content):
            return True
        if mime_type == "application/pdf":
            return True
        return matches_extension(file_name, PDF_EXTENSIONS)
