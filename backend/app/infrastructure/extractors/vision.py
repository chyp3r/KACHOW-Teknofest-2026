import asyncio
import base64
import io
import json
import logging
import urllib.request
from typing import Optional

from app.core.config import settings
from app.core.constants import OCR_RENDER_DPI
from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
    has_pdf_magic_bytes,
    matches_extension,
)

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised via patching in tests
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None

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
    faster.
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
    ) -> ExtractedDocument:
        """Transcribe a scanned document with a vision-language model.

        Args:
            content: Raw PDF or image bytes.
            file_name: Original file name, used to decide the input kind.
            mime_type: Declared content type, used to decide the input kind.

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
            images = await asyncio.to_thread(self._to_images, content, is_pdf)
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
        return ExtractedDocument(
            text=text,
            pages=pages,
            page_count=len(pages),
            extractor=self.name,
            used_ocr=True,
        )

    def _to_images(self, content: bytes, is_pdf: bool) -> list[bytes]:
        """Return one PNG per page, or the image itself when input is an image.

        Args:
            content: Raw PDF or image bytes.
            is_pdf: Whether the content must be rasterised first.

        Returns:
            PNG bytes per page.
        """
        if not is_pdf:
            return [content]

        scale = self.dpi / PDF_POINTS_PER_INCH
        document = pdfium.PdfDocument(content)
        try:
            images = []
            for page in document:
                buffer = io.BytesIO()
                page.render(scale=scale).to_pil().save(buffer, format="PNG")
                images.append(buffer.getvalue())
                page.close()
            return images
        finally:
            document.close()

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
