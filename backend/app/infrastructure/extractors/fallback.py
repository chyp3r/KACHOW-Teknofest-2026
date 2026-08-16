import logging
from typing import Optional

from app.core.constants import (
    HEADER_REPAIR_LINE_COUNT,
    MIN_EXTRACTED_CHAR_COUNT,
    MIN_TEXT_QUALITY_RATIO,
)
from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
)
from app.infrastructure.extractors.vision import OllamaVisionExtractor

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
        header_repair: Optional[OllamaVisionExtractor] = None,
    ) -> None:
        """Initialise the chain.

        Args:
            extractors: Candidate extractors, tried in order.
            min_char_count: Character count at or above which a result may be
                accepted without trying the remaining extractors.
            min_quality_ratio: Share of word-length tokens a result must reach to
                be considered readable.
            header_repair: Optional vision extractor used to repair the header
                band of every OCR result's first page (see
                `_maybe_repair_header`) -- typically the same instance already
                present in `extractors`, passed again here explicitly rather
                than searched for, so a caller that omits it gets a chain with
                no header repair at all instead of silent isinstance-matching.
                None disables the step entirely.
        """
        self.extractors = extractors
        self.min_char_count = min_char_count
        self.min_quality_ratio = min_quality_ratio
        self.header_repair = header_repair

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

    async def _maybe_repair_header(
        self, result: ExtractedDocument, raster_cache: dict
    ) -> ExtractedDocument:
        """Best-effort: replace the header band of an OCR result's first page.

        Applied unconditionally to every OCR result, not gated on any quality
        score: calibrating a trigger (header symbol-noise density) against
        the real scanned corpus this was built for (45 documents under
        datasets/resmi_yazisma/00_gelen_kaynaklar/cevap_yazisi/) found no
        signal that reliably separates documents needing this from those that
        don't -- Pearson r as low as 0.036 once known parser gaps were
        controlled for. Always paying the crop-only vision cost (~12.6s
        measured, not ~26s for a full page) was the deliberate trade accepted
        instead of a working trigger. See HEADER_BAND_FRACTION's own comment.

        Args:
            result: The chain's chosen result. Returned unchanged unless it
                is OCR output with at least one page and a `header_repair`
                extractor was configured.
            raster_cache: The same cache the chain's extractors rasterised
                into -- reused here so no page is rendered a second time.

        Returns:
            `result` with its first page's leading `HEADER_REPAIR_LINE_COUNT`
            lines replaced by the vision model's transcription of that band,
            or `result` completely unchanged on any failure or empty output --
            this step must never turn a working extraction into a failed one.
        """
        if not result.used_ocr or self.header_repair is None or not result.pages:
            return result

        images = raster_cache.get(self.header_repair.dpi)
        if not images:
            return result

        try:
            header_text = await self.header_repair.transcribe_header_band(images[0])
        except Exception:
            logger.warning(
                "Header-band repair failed for [%s]; keeping its original text.",
                result.extractor,
                exc_info=True,
            )
            return result

        header_text = header_text.strip()
        if not header_text:
            return result

        remaining_lines = result.pages[0].splitlines()[HEADER_REPAIR_LINE_COUNT:]
        pages = [
            "\n".join([header_text, *remaining_lines]),
            *result.pages[1:],
        ]
        logger.info(
            "Repaired the header band of [%s]'s first page (%d characters).",
            result.extractor,
            len(header_text),
        )
        return result.model_copy(
            update={"pages": pages, "text": "\n\n".join(pages).strip()}
        )

    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        raster_cache: Optional[dict] = None,
    ) -> ExtractedDocument:
        """Extract text using the first extractor that produces a usable result.

        Args:
            content: The raw document bytes.
            file_name: Original file name, used for dispatch.
            mime_type: Declared content type, used for dispatch.
            raster_cache: Optional pre-existing raster cache, honoured if this
                chain is itself nested under another caller. Created fresh
                per call otherwise, so a scanned PDF that escalates from one
                OCR extractor to the next in *this* chain reuses the pages
                already rendered, without ever leaking that cache across two
                unrelated documents.

        Returns:
            The first result meeting the threshold, or the richest result seen.

        Raises:
            DocumentExtractionError: If no extractor applies or all of them fail.
        """
        if raster_cache is None:
            raster_cache = {}
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
                    content,
                    file_name=file_name,
                    mime_type=mime_type,
                    raster_cache=raster_cache,
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
                return await self._maybe_repair_header(result, raster_cache)

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
            return await self._maybe_repair_header(best, raster_cache)

        if last_error is not None:
            raise DocumentExtractionError(
                f"Belge metni çıkarılamadı: {last_error}"
            ) from last_error

        if attempted == 0:
            raise DocumentExtractionError(
                "Bu dosya türü için metin çıkarma desteği bulunmuyor."
            )

        raise DocumentExtractionError("Belgeden metin çıkarılamadı.")
