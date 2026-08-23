import logging
from typing import Callable, Optional

from app.core.constants import (
    HEADER_REPAIR_LINE_COUNT,
    MAX_OCR_PAGES,
    MIN_EXTRACTED_CHAR_COUNT,
    MIN_HEADER_FIELD_COUNT,
    MIN_TEXT_QUALITY_RATIO,
)
from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
)
from app.infrastructure.extractors.vision import OllamaVisionExtractor

logger = logging.getLogger(__name__)

#: Fixed key `_maybe_repair_header` memoises the transcribed header text
#: under in its per-`extract()`-call `repair_cache`. A plain constant, not
#: `header_repair.dpi` (unlike `raster_cache`'s contract) -- this cache holds
#: exactly one thing (the crop transcription), not page images keyed by
#: render density, so a descriptive string is clearer than reusing DPI as a
#: key for something DPI doesn't actually vary by within one call.
_REPAIR_TEXT_CACHE_KEY = "header_text"
#: Same role as `_REPAIR_TEXT_CACHE_KEY`, for `_repair_signature`'s
#: full-page transcription -- a distinct key in the same `repair_cache`
#: dict, since the two repair steps are mutually exclusive per document
#: (see `_maybe_repair_page_one`) but share the dict's lifetime.
_REPAIR_PAGE_CACHE_KEY = "full_page_text"


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
        header_field_probe: Optional[Callable[[str], int]] = None,
        min_header_field_count: int = MIN_HEADER_FIELD_COUNT,
        scan_text_layer_probe: Optional[Callable[[bytes], bool]] = None,
        signature_probe: Optional[Callable[[str], bool]] = None,
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
                None disables the step entirely. Also the extractor treated as
                the *full-page* vision escalation for `MAX_OCR_PAGES` (see
                `extract`).
            header_field_probe: Optional callable counting how many of a
                document's prescribed header fields (sayi/tarih/konu/muhatap/
                gonderen_kurum) parse out of a page of text -- typically
                `app.ai.compliance.count_header_fields`. Passed explicitly
                rather than imported directly so this infrastructure-layer
                module never depends on the `app.ai` layer (the same reason
                `header_repair` is injected, not looked up). None disables
                the field-aware acceptance criterion entirely, restoring
                exactly today's char/quality-only acceptance -- see
                `_has_enough_header_fields`.
            min_header_field_count: Minimum `header_field_probe` result page 1
                must reach for a result to be accepted outright, once
                char/quality already passed. Calibrated in
                `MIN_HEADER_FIELD_COUNT`'s own comment; only consulted when
                `header_field_probe` is set.
            scan_text_layer_probe: Optional callable reporting whether a
                document's embedded text layer is scanner-origin junk sitting
                over a full-page scan image (Class A -- see
                `app.infrastructure.extractors.base.is_scanned_text_layer`),
                rather than a genuine born-digital text layer. Widens
                `_maybe_repair_header`'s gate to also repair this class of
                result even though `used_ocr` is False for it. None disables
                that widening, so a caller that omits it keeps header repair
                gated on `used_ocr` alone, exactly as before this parameter
                existed.
            signature_probe: Optional callable reporting whether a
                document's signer name (`imza_sahibi`) parses out of a page
                of text -- typically `app.ai.compliance.has_signature`.
                Injected the same way and for the same reason as
                `header_field_probe`. When it reports the signature
                unparseable, `_maybe_repair_page_one` replaces page 1
                wholesale with a full-page vision transcription instead of
                the header-band-only crop (see `_repair_signature`) --
                header-band repair alone cannot reach a signature block,
                which sits well below the header. None disables the
                signature-recovery escalation entirely, restoring exactly
                today's header-band-only repair.
        """
        self.extractors = extractors
        self.min_char_count = min_char_count
        self.min_quality_ratio = min_quality_ratio
        self.header_repair = header_repair
        self.header_field_probe = header_field_probe
        self.min_header_field_count = min_header_field_count
        self.scan_text_layer_probe = scan_text_layer_probe
        self.signature_probe = signature_probe

    def _is_acceptable(self, result: ExtractedDocument) -> bool:
        """Report whether a result is good enough to stop the chain.

        Both checks are needed. Length alone accepts OCR garbage: on a degraded
        scan Tesseract returned 758 characters of nonsense, comfortably past the
        length threshold, and the chain would have stopped there and reported no
        header fields at all.

        Args:
            result: A candidate extraction.

        Returns:
            True when the result is long enough and readable enough. This is
            deliberately silent about header-field recovery -- see
            `_has_enough_header_fields`, a separate, later-applied criterion.
        """
        return (
            result.char_count >= self.min_char_count
            and result.quality_ratio >= self.min_quality_ratio
        )

    def _page_one(self, result: ExtractedDocument) -> str:
        """The text `header_field_probe`/repair reason about: page 1 only.

        Whole-document scoring hides a page-1 header failure behind a later
        page's own header (a multi-page reply carrying an attached letter
        with its own `Konu:` is the real case this guards against -- see
        `count_header_fields`'s own docstring), so every field-aware decision
        in this class reasons about page 1 specifically, never the join.
        """
        return result.pages[0] if result.pages else result.text

    def _header_field_count(self, result: ExtractedDocument) -> int:
        """How many header fields `header_field_probe` recovers from page 1.

        Returns 0 when no probe is configured, which keeps this component of
        `_rank_key` inert for callers that don't inject one -- ranking then
        reduces to exactly the pre-existing quality-only comparison.
        """
        if self.header_field_probe is None:
            return 0
        return self.header_field_probe(self._page_one(result))

    def _has_enough_header_fields(self, result: ExtractedDocument) -> bool:
        """Report whether page 1's header block actually parsed.

        A document-wide prose-readability average (`quality_ratio`) cannot
        see this: a garbled `sayi` or an unparseable `konu` line can sit
        inside otherwise perfectly readable Turkish prose (measured on a
        real document: 0.85 quality_ratio, zero of five header fields
        recovered). This is the second, later-applied acceptance gate that
        catches it.

        Returns:
            True unconditionally when no `header_field_probe` was
            configured -- this criterion must never reject anything on its
            own for a caller that didn't opt into it.
        """
        if self.header_field_probe is None:
            return True
        return self._header_field_count(result) >= self.min_header_field_count

    def _is_scan_text_layer(self, content: bytes) -> bool:
        """False when no `scan_text_layer_probe` was configured.

        Keeps `_maybe_repair_header`'s widened gate inert by default, same
        shape as `_has_enough_header_fields`'s no-probe default.
        """
        if self.scan_text_layer_probe is None:
            return False
        return self.scan_text_layer_probe(content)

    def _rank_key(self, result: ExtractedDocument) -> tuple[int, float]:
        """Ordering key for best-effort candidate selection.

        Header field count first, `quality_ratio` as the tie-break --
        so when nothing clears either acceptance gate, the candidate that
        recovered the most prescribed header fields wins even over a more
        generally "readable" one, and equal field counts (including the
        universal 0 when no `header_field_probe` is configured) fall back to
        exactly today's readability-only comparison.
        """
        return (self._header_field_count(result), result.quality_ratio)

    async def _rasterise_page_one(self, content: bytes, raster_cache: dict):
        """Return a rasterised page-1 image for vision repair.

        Shared by `_maybe_repair_header` and `_repair_signature` -- both
        need exactly this image, from exactly the same source, at exactly
        `self.header_repair.dpi`, so there is exactly one place that
        reuses `raster_cache` or falls back to rendering fresh.

        Args:
            content: The raw document bytes, needed to self-rasterise page 1
                when `raster_cache` has nothing at `header_repair.dpi` (the
                Class-A case: its extractor never rasterises anything).
            raster_cache: The same cache the chain's extractors rasterised
                into -- reused here so no page is rendered a second time.

        Returns:
            The image, or None when rasterisation isn't possible or fails --
            callers must treat that as "repair unavailable", never retry.
        """
        images = raster_cache.get(self.header_repair.dpi)
        if images:
            return images[0]
        # Never rasterised by this chain at all (Class A: its extractor
        # read the text layer directly and rendered nothing) -- render
        # page 1 ourselves. Deliberately NOT written into raster_cache: a
        # partial, page-1-only entry there would make a later
        # full-document OCR pass silently transcribe only page 1 and drop
        # the rest of the document.
        try:
            return await self.header_repair.render_first_page(content)
        except Exception:
            logger.warning(
                "Could not rasterise page 1 for vision repair; keeping "
                "the original text.",
                exc_info=True,
            )
            return None

    async def _maybe_repair_page_one(
        self,
        result: ExtractedDocument,
        raster_cache: dict,
        content: bytes,
        repair_cache: dict,
    ) -> ExtractedDocument:
        """Repair page 1 with vision -- header band, or, when the signature
        can't be parsed (before or after that crop), the whole page instead.

        Dispatches to exactly one of `_maybe_repair_header` (crop-only,
        today's behaviour) or `_repair_signature` (full-page replacement)
        in the common case -- a document only ever pays one of the two
        vision costs then. `signature_probe` decides which: header-band
        repair alone cannot reach a signature block, which sits well below
        the header band (`HEADER_BAND_FRACTION`), so when the signer's name
        isn't parseable at all, a full-page transcription is what actually
        has a chance at it -- and that transcription already covers the
        header too, so cropping it separately afterwards would be paying
        for the same page twice. See `_repair_signature`'s own docstring
        for the measurement behind this.

        One case pays for both: header-band repair's own splice replaces
        only the leading `HEADER_REPAIR_LINE_COUNT` lines of the page, an
        approximation calibrated for a typical multi-paragraph letter --
        on a short document (measured on the real corpus: CY-003/023/028,
        each a brief one-paragraph reply) the signature block itself can
        sit inside that range, and the splice silently discards it even
        though it parsed fine from the pre-repair text. This is detected
        after the fact, not predicted: if the signature was parseable
        before header-band repair and isn't afterwards, the crop ate it --
        fall through to a full-page transcription of the *original*
        result. Rare (3/23 on the measured corpus) and worth the double
        vision cost when it happens: reporting a real signer as a missing
        required field is worse than one slow upload.

        Args:
            result: The chain's chosen result.
            raster_cache: The same cache the chain's extractors rasterised
                into.
            content: The raw document bytes.
            repair_cache: Per-`extract()`-call memoisation, shared across
                both repair paths (each keyed separately).

        Returns:
            `result`, repaired by whichever path applied, or unchanged if
            none did.
        """
        if self.header_repair is None or not result.pages:
            return result
        if not result.used_ocr and not self._is_scan_text_layer(content):
            return result
        if self.signature_probe is not None and not self.signature_probe(
            self._page_one(result)
        ):
            return await self._repair_signature(
                result, raster_cache, content, repair_cache
            )

        repaired = await self._maybe_repair_header(
            result, raster_cache, content, repair_cache
        )
        if self.signature_probe is not None and not self.signature_probe(
            self._page_one(repaired)
        ):
            logger.info(
                "Header-band repair on [%s] discarded a previously-"
                "parseable signature (short document); escalating to a "
                "full-page transcription instead.",
                result.extractor,
            )
            return await self._repair_signature(
                result, raster_cache, content, repair_cache
            )
        return repaired

    async def _repair_signature(
        self,
        result: ExtractedDocument,
        raster_cache: dict,
        content: bytes,
        repair_cache: dict,
    ) -> ExtractedDocument:
        """Best-effort: replace page 1 entirely with a full-page vision
        transcription, for the one failure mode header-band repair cannot
        reach.

        Header-band repair only ever touches the top `HEADER_BAND_FRACTION`
        of the page, but a signature block sits well below it -- so no
        amount of header-band repair can recover a signer's name garbled
        or destroyed by wet-signature ink over the printed text. Measured
        directly on four real documents where OpenDataLoader/Tesseract lost
        the signature line entirely or mangled it beyond recognition
        (`"İF; BOZDAG ;"` for `"Bekir BOZDAĞ"`): full-page vision
        transcription recovered the correct name on all four (see
        `OllamaVisionExtractor.transcribe_page`'s own docstring).

        Only called once `_maybe_repair_page_one` has already established
        `signature_probe` reports the signature unparseable -- this method
        itself does not re-check that, so it always replaces page 1 when
        it successfully transcribes something.

        Args:
            result: The chain's chosen result.
            raster_cache: The same cache the chain's extractors rasterised
                into -- reused here so no page is rendered a second time.
            content: The raw document bytes, for `_rasterise_page_one`.
            repair_cache: Memoises the full-page transcription across every
                candidate this one `extract()` call repairs, under its own
                key (`_REPAIR_PAGE_CACHE_KEY`) separate from header-band
                repair's -- the two never fire for the same document (see
                `_maybe_repair_page_one`), but share the dict's lifetime.

        Returns:
            `result` with its first page replaced by the vision model's
            full transcription, or `result` completely unchanged on any
            failure or empty output -- this step must never turn a working
            extraction into a failed one.
        """
        if _REPAIR_PAGE_CACHE_KEY in repair_cache:
            page_text = repair_cache[_REPAIR_PAGE_CACHE_KEY]
        else:
            page_one_image = await self._rasterise_page_one(content, raster_cache)
            if page_one_image is None:
                return result
            try:
                page_text = await self.header_repair.transcribe_page(page_one_image)
            except Exception:
                logger.warning(
                    "Full-page signature repair failed for [%s]; keeping "
                    "its original text.",
                    result.extractor,
                    exc_info=True,
                )
                return result
            page_text = page_text.strip()
            repair_cache[_REPAIR_PAGE_CACHE_KEY] = page_text

        if not page_text:
            return result

        pages = [page_text, *result.pages[1:]]
        logger.info(
            "Replaced [%s]'s first page with a full-page vision "
            "transcription (%d characters) -- its signature could not be "
            "parsed from the original.",
            result.extractor,
            len(page_text),
        )
        return result.model_copy(
            update={"pages": pages, "text": "\n\n".join(pages).strip()}
        )

    async def _maybe_repair_header(
        self,
        result: ExtractedDocument,
        raster_cache: dict,
        content: bytes,
        repair_cache: dict,
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

        Also widened, via `scan_text_layer_probe`, to a second class of
        result: a "Class A" scanner text layer (see
        `app.infrastructure.extractors.base.is_scanned_text_layer`) has
        `used_ocr=False` -- OpenDataLoader/Pdfium read it as if it were a
        genuine text layer -- but is exactly as corrupted as real OCR output,
        so it needs the same repair despite the flag.

        Args:
            result: The chain's chosen result. Returned unchanged unless it
                is OCR output (or a Class-A scan text layer) with at least
                one page and a `header_repair` extractor was configured.
            raster_cache: The same cache the chain's extractors rasterised
                into -- reused here so no page is rendered a second time.
            content: The raw document bytes, needed to self-rasterise page 1
                when `raster_cache` has nothing at `header_repair.dpi` (the
                Class-A case: its extractor never rasterises anything).
            repair_cache: Memoises the crop transcription across every
                candidate this one `extract()` call repairs -- the crop is
                identical for all of them (same image, same model,
                temperature 0), so without this a document that escalates
                past several candidates would pay the vision-model cost once
                per candidate instead of once per document.

        Returns:
            `result` with its first page's leading `HEADER_REPAIR_LINE_COUNT`
            lines replaced by the vision model's transcription of that band,
            or `result` completely unchanged on any failure or empty output --
            this step must never turn a working extraction into a failed one.
        """
        if self.header_repair is None or not result.pages:
            return result
        if not result.used_ocr and not self._is_scan_text_layer(content):
            return result

        if _REPAIR_TEXT_CACHE_KEY in repair_cache:
            header_text = repair_cache[_REPAIR_TEXT_CACHE_KEY]
        else:
            page_one_image = await self._rasterise_page_one(content, raster_cache)
            if page_one_image is None:
                return result

            try:
                header_text = await self.header_repair.transcribe_header_band(
                    page_one_image
                )
            except Exception:
                logger.warning(
                    "Header-band repair failed for [%s]; keeping its "
                    "original text.",
                    result.extractor,
                    exc_info=True,
                )
                return result
            header_text = header_text.strip()
            repair_cache[_REPAIR_TEXT_CACHE_KEY] = header_text

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

        A candidate must clear two independent gates to be returned outright:
        `_is_acceptable` (long enough, readable enough) and, once that
        passes and header repair has had its chance,
        `_has_enough_header_fields` (page 1's prescribed fields actually
        parsed). A candidate that clears the first but not the second does
        not return -- it becomes a best-effort candidate like any
        char/quality rejection, and the chain tries the next extractor. This
        is what lets the chain reach the last-resort vision extractor for a
        document like a Class-A scan whose text reads as fine Turkish prose
        overall but whose header block is corrupted.

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
            The first result meeting both gates, or the richest result seen.

        Raises:
            DocumentExtractionError: If no extractor applies or all of them fail.
        """
        if raster_cache is None:
            raster_cache = {}
        # Memoises the header-band crop transcription across every candidate
        # this call repairs -- see `_maybe_repair_header`'s own docstring.
        # Fresh per `extract()` call, same lifetime as `raster_cache`, so
        # nothing leaks across two unrelated documents.
        repair_cache: dict = {}
        best: Optional[ExtractedDocument] = None
        # Whether `best` already went through `_maybe_repair_header` inside
        # the loop below. Repairing it a second time at the loop-exit return
        # would re-replace its first HEADER_REPAIR_LINE_COUNT lines -- which
        # by then are the repaired header plus real body lines -- silently
        # deleting body text (a double splice).
        best_repaired = False
        last_error: Optional[Exception] = None
        attempted = 0
        # The most recently seen page count, from whichever extractor last
        # ran -- used only to decide whether the *full-page* vision
        # escalation (as opposed to header-band repair, which is always
        # page-1-only regardless of document length) is worth its cost. See
        # MAX_OCR_PAGES's own comment.
        known_page_count: Optional[int] = None

        for extractor in self.extractors:
            if not extractor.supports(
                content, file_name=file_name, mime_type=mime_type
            ):
                continue

            if (
                extractor is self.header_repair
                and known_page_count is not None
                and known_page_count > MAX_OCR_PAGES
            ):
                logger.info(
                    "Skipping full-page vision escalation for [%s]: %d "
                    "page(s) exceeds the %d-page cap; header-band repair "
                    "still applies to whichever result is chosen.",
                    extractor.name,
                    known_page_count,
                    MAX_OCR_PAGES,
                )
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

            known_page_count = result.page_count

            if not self._is_acceptable(result):
                logger.info(
                    "Extractor [%s] rejected: %d characters (threshold %d), "
                    "quality %.2f (threshold %.2f); trying the next one.",
                    extractor.name,
                    result.char_count,
                    self.min_char_count,
                    result.quality_ratio,
                    self.min_quality_ratio,
                )
                if best is None or self._rank_key(result) > self._rank_key(best):
                    best = result
                    best_repaired = False
                continue

            logger.info(
                "Extractor [%s] accepted with %d characters (quality %.2f).",
                extractor.name,
                result.char_count,
                result.quality_ratio,
            )
            result = await self._maybe_repair_page_one(
                result, raster_cache, content, repair_cache
            )

            if self._has_enough_header_fields(result):
                return result

            logger.warning(
                "Extractor [%s] accepted but recovered only %d of the "
                "prescribed header fields on page 1 (floor %d); trying the "
                "next one.",
                extractor.name,
                self._header_field_count(result),
                self.min_header_field_count,
            )
            if best is None or self._rank_key(result) > self._rank_key(best):
                best = result
                best_repaired = True

        if best is not None:
            logger.warning(
                "No extractor met the acceptance criteria; returning the "
                "best result from [%s] with %d characters.",
                best.extractor,
                best.char_count,
            )
            if best_repaired:
                return best
            return await self._maybe_repair_page_one(
                best, raster_cache, content, repair_cache
            )

        if last_error is not None:
            raise DocumentExtractionError(
                f"Belge metni çıkarılamadı: {last_error}"
            ) from last_error

        if attempted == 0:
            raise DocumentExtractionError(
                "Bu dosya türü için metin çıkarma desteği bulunmuyor."
            )

        raise DocumentExtractionError("Belgeden metin çıkarılamadı.")
