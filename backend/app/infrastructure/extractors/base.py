import re
from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field

PDF_MAGIC_BYTES = b"%PDF"

#: Word-ish token: letters and digits, Turkish characters included.
_TOKEN_PATTERN = re.compile(r"[0-9A-Za-zÇĞİÖŞÜçğıöşü]+")
#: Tokens this long or longer are treated as real words rather than OCR noise.
_WORD_MIN_LENGTH = 3


class DocumentExtractionError(Exception):
    """Raised when a document's text cannot be extracted.

    Deliberately a plain exception rather than an `app.api.exceptions` subclass so
    the infrastructure layer stays independent of the HTTP layer. The domain
    service is responsible for translating it into an API exception.
    """


class ExtractedDocument(BaseModel):
    """Text and provenance of a document parsed out of raw uploaded bytes."""

    text: str = Field(description="Belgeden çıkarılan tam metin.")
    pages: list[str] = Field(
        default_factory=list, description="Sayfa sayfa çıkarılan metin parçaları."
    )
    page_count: int = Field(default=0, description="İşlenen sayfa sayısı.")
    extractor: str = Field(
        description="Metni çıkaran bileşenin adı (örn. 'opendataloader')."
    )
    used_ocr: bool = Field(
        default=False,
        description="Metin OCR ile okunduysa true; alan değerleri doğrulanmalıdır.",
    )

    @property
    def char_count(self) -> int:
        """Number of non-whitespace-stripped characters in the extracted text."""
        return len(self.text.strip())

    @property
    def quality_ratio(self) -> float:
        """Fraction of tokens long enough to be real words rather than OCR noise.

        Character count alone cannot tell a good result from a bad one: OCR run on
        a degraded scan happily returns hundreds of characters of nonsense, which
        clears any length threshold. Failed recognition fragments text into one and
        two character pieces, so the share of word-length tokens separates the two
        cleanly -- measured on this project's corpus, readable Turkish scores about
        0.80 and unusable output about 0.39.

        Returns:
            Ratio between 0.0 and 1.0; 0.0 when there is no text at all.
        """
        tokens = _TOKEN_PATTERN.findall(self.text)
        if not tokens:
            return 0.0
        readable = [token for token in tokens if len(token) >= _WORD_MIN_LENGTH]
        return len(readable) / len(tokens)


class BaseDocumentExtractor(ABC):
    """Abstract text extractor turning raw document bytes into `ExtractedDocument`.

    Takes bytes rather than a path on purpose: both callers already hold bytes
    (`UploadFile.read()` and `BaseStorage.get_file()`), and the S3 storage backend
    has no local path at all. Adapters that wrap a path-based or file-based tool
    are responsible for their own temporary files.
    """

    #: Short identifier recorded in `ExtractedDocument.extractor`.
    name: str = "base"

    @abstractmethod
    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> ExtractedDocument:
        """Extract text from raw document bytes.

        Args:
            content: The raw document bytes.
            file_name: Original file name, used for extension-based dispatch.
            mime_type: Declared content type, used for dispatch.

        Returns:
            The extracted text along with page breakdown and provenance.

        Raises:
            DocumentExtractionError: If this extractor cannot parse the input.
        """

    def supports(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> bool:
        """Report whether this extractor should be attempted for the given input.

        Guarding the chain matters: without it a plain-text extractor would decode
        PDF bytes into a large blob of replacement characters, clear the minimum
        character threshold, and win over the extractor that can actually read it.

        Args:
            content: The raw document bytes.
            file_name: Original file name.
            mime_type: Declared content type.

        Returns:
            True when this extractor is applicable to the input.
        """
        return True


def has_pdf_magic_bytes(content: bytes) -> bool:
    """Report whether the buffer starts with the PDF file signature.

    Args:
        content: The raw document bytes.

    Returns:
        True when the content is a PDF regardless of the declared MIME type.
    """
    return content[:4] == PDF_MAGIC_BYTES


def matches_extension(file_name: Optional[str], extensions: set[str]) -> bool:
    """Report whether a file name ends with one of the given extensions.

    Args:
        file_name: File name to inspect; may be None.
        extensions: Lower-case extensions without a leading dot.

    Returns:
        True when the file name carries one of the extensions.
    """
    if not file_name or "." not in file_name:
        return False
    return file_name.rsplit(".", 1)[1].lower() in extensions
