import logging
from typing import Optional

from app.core.constants import MIN_EXTRACTED_CHAR_COUNT
from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
)

logger = logging.getLogger(__name__)


class FallbackDocumentExtractor(BaseDocumentExtractor):
    """Tries an ordered chain of extractors until one returns enough text.

    Exists so that extraction *policy* — which parser to try, when a result is
    too thin to trust, when to escalate to OCR — lives in one testable place
    instead of being spread through the domain service. The service depends only
    on `BaseDocumentExtractor` and never learns that a chain exists.
    """

    name = "fallback"

    def __init__(
        self,
        extractors: list[BaseDocumentExtractor],
        min_char_count: int = MIN_EXTRACTED_CHAR_COUNT,
    ) -> None:
        """Initialise the chain.

        Args:
            extractors: Candidate extractors, tried in order.
            min_char_count: Character count at or above which a result is accepted
                without trying the remaining extractors.
        """
        self.extractors = extractors
        self.min_char_count = min_char_count

    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> ExtractedDocument:
        """Extract text using the first extractor that produces a usable result.

        Args:
            content: The raw document bytes.
            file_name: Original file name, used for dispatch.
            mime_type: Declared content type, used for dispatch.

        Returns:
            The first result meeting the threshold, or the richest result seen.

        Raises:
            DocumentExtractionError: If no extractor applies or all of them fail.
        """
        best: Optional[ExtractedDocument] = None
        last_error: Optional[Exception] = None
        attempted = 0

        for extractor in self.extractors:
            if not extractor.supports(
                content, file_name=file_name, mime_type=mime_type
            ):
                continue

            attempted += 1
            try:
                result = await extractor.extract(
                    content, file_name=file_name, mime_type=mime_type
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Extractor [%s] failed, trying the next one: %s",
                    extractor.name,
                    exc,
                )
                continue

            if result.char_count >= self.min_char_count:
                logger.info(
                    "Extractor [%s] accepted with %d characters.",
                    extractor.name,
                    result.char_count,
                )
                return result

            logger.info(
                "Extractor [%s] returned only %d characters (threshold %d); "
                "trying the next one.",
                extractor.name,
                result.char_count,
                self.min_char_count,
            )
            if best is None or result.char_count > best.char_count:
                best = result

        if best is not None:
            logger.warning(
                "No extractor met the %d character threshold; returning the best "
                "result from [%s] with %d characters.",
                self.min_char_count,
                best.extractor,
                best.char_count,
            )
            return best

        if last_error is not None:
            raise DocumentExtractionError(
                f"Belge metni çıkarılamadı: {last_error}"
            ) from last_error

        if attempted == 0:
            raise DocumentExtractionError(
                "Bu dosya türü için metin çıkarma desteği bulunmuyor."
            )

        raise DocumentExtractionError("Belgeden metin çıkarılamadı.")
