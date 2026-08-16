import asyncio
import base64
import io
import json
import logging
import urllib.request
from typing import Optional

from app.core.config import settings
from app.core.constants import HEADER_BAND_FRACTION, OCR_RENDER_DPI
from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
    has_pdf_magic_bytes,
    matches_extension,
)
from app.infrastructure.extractors.marks import detect_marks

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised via patching in tests
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None

try:  # pragma: no cover
    from PIL import Image as _PILImage
except ImportError:  # pragma: no cover
    _PILImage = None

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "gif", "webp"}
PDF_EXTENSIONS = {"pdf"}
PDF_POINTS_PER_INCH = 72
#: Transcription instruction, in English on purpose.
#:
#: This used to be the Turkish "Bu belgedeki tüm metni olduğu gibi, satır yapısını
#: koruyarak çıkar." Asking a model to read Turkish in Turkish looks obviously
#: right and measured as the worst option for every model tried, including the one
#: shipped at the time: glm-ocr went from NED 0.164 to 0.145 purely by dropping the
#: Turkish wording, and deepseek-ocr went from a total failure (NED 1.000, empty
#: output) to its best result. The instruction language is not the transcription
#: language -- these models follow English instructions far more reliably, and the
#: text they transcribe is unaffected by the language they were asked in.
#:
#: Changing this and `settings.OLLAMA_VISION_MODEL` are coupled: deepseek-ocr
#: returns nothing at all under the old Turkish prompt.
DEFAULT_PROMPT = "Extract all text from this document exactly as it appears."
#: Generous enough for a full page of Turkish official correspondence. Left unset,
#: Ollama truncates the transcription part-way through a field value.
DEFAULT_NUM_PREDICT = 4096
DEFAULT_NUM_CTX = 8192
REQUEST_TIMEOUT_SECONDS = 300


class OllamaVisionExtractor(BaseDocumentExtractor):
    """OCR via a local vision-language model served by Ollama.

    Complements `TesseractExtractor` rather than replacing it. Measured on this
    project's corpus, Tesseract is both more accurate and roughly seventy times
    faster on clean 300 DPI renders. On degraded scans -- skewed, blurred,
    low-contrast, JPEG-compressed, the way a photocopied or photographed evrak
    actually arrives -- Tesseract collapses, recovering **1 of 62** header fields
    across the sample corpus where this model recovers 58.

    So the chain keeps Tesseract first for speed and escalates here only when the
    result fails the readability check.

    On model choice (see `scripts/evaluate_ocr_fields.py`): candidates are judged
    on how many prescribed fields survive, not on how well the text reads, and the
    two disagree sharply. Over 12 degraded evrak carrying 62 labelled fields:

    ==========================  ==========  ==========  ============
    model                       found       exact       OCRTurk tokF1
    ==========================  ==========  ==========  ============
    tesseract                   1/62        0/62        0.411
    glm-ocr                     59/62       35/62       0.676
    deepseek-ocr (current)      58/62       48/62       0.846
    frob/unlimited-ocr:q8_0     0/62        0/62        0.708
    ==========================  ==========  ==========  ============

    `frob/unlimited-ocr` is why the field metric exists. It out-scores glm-ocr on
    text fidelity and recovers **zero** fields -- it reads the Turkish accurately
    but reformats the page, and a header the parser cannot find is reported as
    missing information. Text metrics cannot see that failure.

    glm-ocr and deepseek-ocr find the same fields (59 vs 58, trading wins and
    losses document by document -- noise at this sample size). They differ on
    whether the *value* is right, and there deepseek-ocr is decisively ahead:
    48 exact against 35. Same missing-field accuracy, far fewer wrong values, and
    faster on the synthetic corpus above -- which decided the original default.

    That synthetic corpus (12 documents, one degradation profile) did not hold up
    against real scans. Re-measured on `scripts/evaluate_ocr_real.py`'s 19
    hand-labelled real `CY-*.pdf` documents (76 fields, `datasets/resmi_yazisma/
    ocr_ground_truth.json`), scored through the real production chain
    (Tesseract + header-band repair), not raw full-page transcription:

    ======================  ===========  ===========  =====
    engine                  zincir bul.  zincir tam   süre
    ======================  ===========  ===========  =====
    tesseract               64/76        32/76         54s
    deepseek-ocr (was)      65/76        42/76        730s
    glm-ocr:latest (now)    67/76        50/76       1579s
    ======================  ===========  ===========  =====

    glm-ocr:latest recovers more fields and gets more of them exactly right --
    roughly a 19% relative gain in exact match -- at roughly double the
    wall-clock. That tradeoff was made deliberately in favour of accuracy: this
    project's compliance checker reports a wrong value as if it were correct,
    which is worse than reporting a field as missing.

    This also settled a specific question raised during that investigation: a
    torch/transformers deployment of the *same* GLM-OCR weights
    (`zai-org/GLM-OCR`, see `scripts/ocr_sidecar.py`) does **not** beat this
    Ollama-served version -- 46/76 exact against 50/76, after fixing a genuine
    bug in the comparison harness (it fed the model an un-downscaled 300 DPI
    page; capping input resolution -- see `ocr_sidecar.MAX_IMAGE_DIMENSION` --
    fixed that and reversed an earlier, wrong "transformers is much faster"
    reading, but did not close the accuracy gap). No transformers deployment
    ships as a result: the Ollama-served model already wins.
    """

    name = "ollama_vision"

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        dpi: int = OCR_RENDER_DPI,
        prompt: str = DEFAULT_PROMPT,
    ) -> None:
        """Initialise the vision extractor.

        Args:
            model: Ollama vision model tag; defaults to `settings.OLLAMA_VISION_MODEL`.
            base_url: Ollama endpoint; defaults to `settings.OLLAMA_BASE_URL`.
            dpi: Rasterisation density for PDF pages.
            prompt: Turkish transcription instruction.
        """
        self.model = model or settings.OLLAMA_VISION_MODEL
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.dpi = dpi
        self.prompt = prompt

    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        raster_cache: Optional[dict] = None,
    ) -> ExtractedDocument:
        """Transcribe a scanned document with a vision-language model.

        Args:
            content: Raw PDF or image bytes.
            file_name: Original file name, used to decide the input kind.
            mime_type: Declared content type, used to decide the input kind.
            raster_cache: Optional shared cache of already-rasterised pages,
                keyed by DPI (see `BaseDocumentExtractor.extract`). This
                extractor is the usual escalation *after*
                `TesseractExtractor` rejects a result, so the common case is
                a cache hit -- reusing pages already rendered at the same
                DPI instead of rasterising the same PDF a second time.

        Returns:
            The transcribed text, flagged as OCR output.

        Raises:
            DocumentExtractionError: If rasterisation or the model call fails.
        """
        is_pdf = has_pdf_magic_bytes(content) or mime_type == "application/pdf"
        if is_pdf and pdfium is None:
            raise DocumentExtractionError(
                "pypdfium2 kurulu değil; PDF görüntüye çevrilemedi."
            )

        try:
            if not is_pdf:
                images = [content]
                # Decoded only for mark detection below (see its own
                # try/except) -- the transcription call above never needed a
                # PIL object for this branch, so a decode failure here must
                # not break transcription, which is why this is not folded
                # into the same try/except as the rest of this method.
                pil_pages = []
                if _PILImage is not None:
                    try:
                        pil_pages = [await asyncio.to_thread(_PILImage.open, io.BytesIO(content))]
                    except Exception:
                        logger.warning("Could not decode image for mark detection.", exc_info=True)
            else:
                if raster_cache is not None and self.dpi in raster_cache:
                    pil_pages = raster_cache[self.dpi]
                    logger.info(
                        "Reusing %d already-rasterised page(s) at %d DPI.",
                        len(pil_pages),
                        self.dpi,
                    )
                else:
                    pil_pages = await asyncio.to_thread(self._render_pages, content)
                    if raster_cache is not None:
                        raster_cache[self.dpi] = pil_pages
                images = await asyncio.to_thread(self._encode_png, pil_pages)
            # Deliberately sequential, unlike TesseractExtractor's page loop.
            # Tesseract pages parallelise safely because each OCR call is its
            # own `tesseract` subprocess, competing for CPU cores the OS
            # already schedules. A vision-model call is a generation request
            # against one Ollama-served model; Ollama serialises generation
            # against a given model rather than running requests on it
            # concurrently, so concurrent page requests would queue behind
            # each other on the server side regardless of client-side
            # fan-out -- the same shape of cost this project already measured
            # as a net loss for concurrent classify+extract calls against the
            # same model. Revisit only with a live Ollama instance to measure
            # against; guessing wrong here costs latency on OllamaVisionExtractor
            # specifically, which is already the last-resort path for the
            # hardest-to-read documents.
            pages = [await asyncio.to_thread(self._transcribe, img) for img in images]
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError(
                f"Görsel dil modeli ile OCR başarısız oldu: {exc}"
            ) from exc

        text = "\n\n".join(pages).strip()
        logger.info(
            "OllamaVisionExtractor (%s) transcribed %d page(s), %d characters.",
            self.model,
            len(pages),
            len(text),
        )
        # Best-effort, same rendered pages: detect_marks never raises (see
        # its own docstring), so a detector bug here must never fail a
        # transcription that otherwise succeeded.
        mark_lists = await asyncio.gather(
            *(
                asyncio.to_thread(detect_marks, image, page_number)
                for page_number, image in enumerate(pil_pages, start=1)
            )
        )
        return ExtractedDocument(
            text=text,
            pages=pages,
            page_count=len(pages),
            extractor=self.name,
            used_ocr=True,
            detected_marks=[mark for marks in mark_lists for mark in marks],
        )

    def _render_pages(self, content: bytes) -> list:
        """Rasterise every page of a PDF to a PIL image, in document order.

        Kept separate from PNG encoding (`_encode_png`) so the raw rendered
        pages are what goes into `raster_cache` -- the same shape
        `TesseractExtractor` caches, and reusable for any future consumer
        that doesn't specifically need PNG bytes.

        Args:
            content: Raw PDF bytes.

        Returns:
            One rendered PIL image per page.
        """
        scale = self.dpi / PDF_POINTS_PER_INCH
        document = pdfium.PdfDocument(content)
        try:
            images = []
            for page in document:
                bitmap = page.render(scale=scale)
                try:
                    images.append(bitmap.to_pil())
                finally:
                    page.close()
            return images
        finally:
            document.close()

    def _encode_png(self, images: list) -> list[bytes]:
        """Encode PIL images to PNG bytes, the format Ollama's API expects.

        Args:
            images: PIL images, in document order.

        Returns:
            PNG-encoded bytes per image, same order.
        """
        encoded = []
        for image in images:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            encoded.append(buffer.getvalue())
        return encoded

    def _transcribe(self, image: bytes) -> str:
        """Send one page image to the model and return its transcription.

        Args:
            image: PNG bytes of a single page.

        Returns:
            The transcribed text.
        """
        payload = {
            "model": self.model,
            "prompt": self.prompt,
            "images": [base64.b64encode(image).decode()],
            "stream": False,
            "options": {
                "temperature": 0,
                "num_predict": DEFAULT_NUM_PREDICT,
                "num_ctx": DEFAULT_NUM_CTX,
            },
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            return json.load(response).get("response", "")

    def supports(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> bool:
        """Accept PDFs and raster images; reject anything textual."""
        if has_pdf_magic_bytes(content) or mime_type == "application/pdf":
            return True
        if mime_type and mime_type.startswith("image/"):
            return True
        return matches_extension(file_name, IMAGE_EXTENSIONS | PDF_EXTENSIONS)

    async def transcribe_header_band(self, page_image) -> str:
        """Transcribe just the header band of one already-rasterised page.

        Used by `FallbackDocumentExtractor`'s header-repair step, not by this
        class's own `extract()`. Crops the top `HEADER_BAND_FRACTION` of the
        page and sends only that crop through the same model call a full-page
        transcription uses -- a small crop costs a fraction of the time
        (measured directly: ~12.6s, against ~26s for a full page on the same
        model) for specifically the part of a scan this project's OCR chain
        struggles with (letterhead emblems, handwritten annotations), without
        paying that cost on the body text Tesseract already reads well.

        Args:
            page_image: A rasterised PIL page image, e.g. from `raster_cache`
                (the same shape `TesseractExtractor` and this class's own
                `extract()` share a cache entry for).

        Returns:
            The crop's transcription. May be empty on a genuine blank header;
            callers should treat that the same as any other best-effort
            failure, not retry.

        Raises:
            DocumentExtractionError: If the model call itself fails.
        """
        width, height = page_image.size
        crop = page_image.crop((0, 0, width, int(height * HEADER_BAND_FRACTION)))
        try:
            encoded = await asyncio.to_thread(self._encode_png, [crop])
            return await asyncio.to_thread(self._transcribe, encoded[0])
        except Exception as exc:
            raise DocumentExtractionError(
                f"Görsel dil modeli ile başlık onarımı başarısız oldu: {exc}"
            ) from exc
