import logging
from typing import Optional

from app.core.constants import MIN_EXTRACTED_CHAR_COUNT, MIN_TEXT_QUALITY_RATIO
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
        min_quality_ratio: float = MIN_TEXT_QUALITY_RATIO,
    ) -> None:
        """Initialise the chain.

        Args:
            extractors: Candidate extractors, tried in order.
            min_char_count: Character count at or above which a result may be
                accepted without trying the remaining extractors.
            min_quality_ratio: Share of word-length tokens a result must reach to
                be considered readable.
        """
        self.extractors = extractors
        self.min_char_count = min_char_count
        self.min_quality_ratio = min_quality_ratio

    def _is_acceptable(self, result: ExtractedDocument) -> bool:
        """Report whether a result is good enough to stop the chain.

        Both checks are needed. Length alone accepts OCR garbage: on a degraded
        scan Tesseract returned 758 characters of nonsense, comfortably past the
        length threshold, and the chain would have stopped there and reported no
        header fields at all.

        Args:
            result: A candidate extraction.

        Returns:
            True when the result is long enough and readable enough.
        """
        return (
            result.char_count >= self.min_char_count
            and result.quality_ratio >= self.min_quality_ratio
        )

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

            if self._is_acceptable(result):
                logger.info(
                    "Extractor [%s] accepted with %d characters (quality %.2f).",
                    extractor.name,
                    result.char_count,
                    result.quality_ratio,
                )
                return result

            logger.info(
                "Extractor [%s] rejected: %d characters (threshold %d), quality "
                "%.2f (threshold %.2f); trying the next one.",
                extractor.name,
                result.char_count,
                self.min_char_count,
                result.quality_ratio,
                self.min_quality_ratio,
            )
            # Rank best-effort candidates by readability rather than sheer length,
            # so a short clean result beats a long unreadable one.
            if best is None or result.quality_ratio > best.quality_ratio:
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
