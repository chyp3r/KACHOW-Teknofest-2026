import asyncio
import contextlib
import logging
import os
import re
import tempfile
from typing import Iterator, Optional

from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
    has_pdf_magic_bytes,
    has_pdf_text_layer,
    matches_extension,
)

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised via patching in tests
    from langchain_opendataloader_pdf import OpenDataLoaderPDFLoader
except ImportError:  # pragma: no cover
    OpenDataLoaderPDFLoader = None

PDF_EXTENSIONS = {"pdf"}

#: Matches a leading ATX heading marker ("#" through "######" followed by
#: whitespace) at the start of a line, and nothing else -- table pipes and a
#: '#' inside body text are untouched.
#:
#: `output_format="markdown"` injects this syntax onto ordinary header lines
#: (observed: "##### TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA" and
#: "### Konu : Soru Önergesi" on real CY-034/ANKARA_BSB documents), which then
#: leaks verbatim into a parsed field value -- the parser's own anchors
#: (`(?:^|\n)\s*Konu`) also cannot cross the marker, so a heading-prefixed
#: line can silently prevent a field from parsing at all. It is this
#: extractor's own formatting choice, not a property of the document, so it
#: is stripped here rather than in the parser -- cleaning the text once for
#: every downstream consumer (parser, classifier prompt, Q&A chunking,
#: detailed summary, the text-view UI) instead of leaving '#'s visible in
#: whichever one a person or another model reads first.
_MARKDOWN_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE)


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
        raster_cache: Optional[dict] = None,
    ) -> ExtractedDocument:
        """Parse a PDF into per-page text using OpenDataLoader.

        Args:
            content: The raw PDF bytes.
            file_name: Original file name (unused).
            mime_type: Declared content type (unused).
            raster_cache: Unused; this extractor reads the PDF's own text
                layer and never rasterises anything.

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
                # Line structure in an official document header is semantically
                # load-bearing: "Sayı" and "Tarih" share a line, "Konu" sits below,
                # and the signature block is name-then-title. With the default
                # collapsing, field extraction misses tarih/konu outright and
                # misassigns the signer to unrelated fields.
                keep_line_breaks=True,
                quiet=True,
            )
            documents = loader.load()
        return [
            _MARKDOWN_HEADING.sub("", document.page_content) for document in documents
        ]

    def supports(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> bool:
        """Accept PDFs with a text layer; reject genuine scans outright.

        A scanned PDF has nothing for this extractor to find -- it always
        rejects, but not before paying OpenDataLoader's JVM startup cost to
        find that out. `has_pdf_text_layer` is a cheap, no-JVM probe that
        catches this ahead of time so a scan skips straight to the OCR
        extractors instead.
        """
        is_pdf = (
            has_pdf_magic_bytes(content)
            or mime_type == "application/pdf"
            or matches_extension(file_name, PDF_EXTENSIONS)
        )
        return is_pdf and has_pdf_text_layer(content)
