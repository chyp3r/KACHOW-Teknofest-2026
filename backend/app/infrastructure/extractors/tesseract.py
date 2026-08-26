import asyncio
import io
import logging
from typing import Optional

from app.core.constants import (
    OCR_LANGUAGE,
    OCR_PAGE_SEGMENTATION_MODE,
    OCR_RENDER_DPI,
)
from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
    has_pdf_magic_bytes,
    matches_extension,
)
from app.infrastructure.extractors.marks import detect_marks

logger = logging.getLogger(__name__)

try:  # pragma: no cover - testlerde patch ile çalıştırılır
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None

try:  # pragma: no cover
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None

try:  # pragma: no cover
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "gif", "webp"}
PDF_EXTENSIONS = {"pdf"}
PDF_POINTS_PER_INCH = 72


class TesseractExtractor(BaseDocumentExtractor):
    """Taranmış PDF'ler ve fotoğraflanmış belgeler için Türkçe OCR çıkarıcısı.

    Tesseract yalnızca görüntü okur -- girdi formatları Leptonica'dan gelir ve
    PDF içermez -- bu yüzden PDF girdisi önce `OCR_RENDER_DPI` yoğunluğunda
    PDFium ile rasterize edilir. Düşük ölçeklendirme, zayıf Türkçe karakter
    tanımanın başlıca nedenidir, bu yüzden yoğunluk bir varsayılan değil,
    adlandırılmış bir sabittir.
    """

    name = "tesseract"

    def __init__(
        self,
        language: str = OCR_LANGUAGE,
        dpi: int = OCR_RENDER_DPI,
        page_segmentation_mode: int = OCR_PAGE_SEGMENTATION_MODE,
    ) -> None:
        """OCR çıkarıcısını başlat.

        Args:
            language: Tesseract dil paketi, örn. "tur".
            dpi: PDF sayfaları için kullanılan rasterizasyon yoğunluğu.
            page_segmentation_mode: Tesseract `--psm` değeri.
        """
        self.language = language
        self.dpi = dpi
        self.page_segmentation_mode = page_segmentation_mode

    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        raster_cache: Optional[dict] = None,
    ) -> ExtractedDocument:
        """Taranmış bir PDF'de veya görüntüde metni tanı.

        Args:
            content: Ham PDF veya görüntü byte'ları.
            file_name: Girdi türüne karar vermek için kullanılan orijinal dosya adı.
            mime_type: Girdi türüne karar vermek için kullanılan bildirilen içerik türü.
            raster_cache: DPI'ya göre anahtarlanmış, zaten rasterize edilmiş
                sayfaların isteğe bağlı paylaşılan önbelleği (bkz.
                `BaseDocumentExtractor.extract`). Render etmeden önce
                kontrol edilir, sonra doldurulur; böylece aynı DPI'da
                `OllamaVisionExtractor`'a yükselme, aynı PDF'i ikinci kez
                rasterize etmek yerine bu sayfaları yeniden kullanır.

        Returns:
            OCR çıktısı olarak işaretlenmiş, sayfa başına bir girdi olan tanınan metin.

        Raises:
            DocumentExtractionError: Bir bağımlılık eksikse veya OCR başarısız olursa.
        """
        if pytesseract is None or Image is None:
            raise DocumentExtractionError(
                "pytesseract veya Pillow kurulu değil; OCR yapılamadı."
            )

        is_pdf = has_pdf_magic_bytes(content) or mime_type == "application/pdf"
        if is_pdf and pdfium is None:
            raise DocumentExtractionError(
                "pypdfium2 kurulu değil; taranmış PDF OCR için görüntüye çevrilemedi."
            )

        try:
            if not is_pdf:
                images = [await asyncio.to_thread(Image.open, io.BytesIO(content))]
            elif raster_cache is not None and self.dpi in raster_cache:
                images = raster_cache[self.dpi]
                logger.info("Reusing %d already-rasterised page(s) at %d DPI.", len(images), self.dpi)
            else:
                images = await asyncio.to_thread(self._render_pages, content)
                if raster_cache is not None:
                    raster_cache[self.dpi] = images
            # Her pytesseract çağrısı kendi `tesseract` alt sürecinde bloklanır,
            # bu da süre boyunca GIL'i serbest bırakır -- buradaki eşzamanlı
            # thread'ler Python tarafından sıralanmış değil, gerçekten ayrı
            # işletim sistemi süreçleri olarak çalışır. Render etme yukarıda
            # sıralı kalır (pdfium sayfa başına zaten hızlı; asıl maliyet
            # burada paralelleştirilen OCR'dir).
            pages = await asyncio.gather(
                *(asyncio.to_thread(self._ocr_image, image) for image in images)
            )
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError(f"OCR sırasında hata oluştu: {exc}") from exc

        text = "\n\n".join(pages).strip()
        logger.info(
            "TesseractExtractor recognised %d page(s), %d characters (lang=%s, dpi=%d).",
            len(pages),
            len(text),
            self.language,
            self.dpi,
        )
        # En iyi çaba, aynı render edilmiş sayfalar: detect_marks asla exception
        # fırlatmaz (kendi docstring'ine bakın), bu yüzden buradaki bir dedektör
        # hatası aksi halde başarılı olan bir OCR sonucunu asla başarısız
        # kılmamalı -- bu çağrı noktasında try/except gerekmez.
        mark_lists = await asyncio.gather(
            *(
                asyncio.to_thread(detect_marks, image, page_number)
                for page_number, image in enumerate(images, start=1)
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
        """Bir PDF'in her sayfasını belge sırasına göre PIL görüntüsüne rasterize et.

        Args:
            content: Ham PDF byte'ları.

        Returns:
            Sayfa başına bir render edilmiş PIL görüntüsü.
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

    def _ocr_image(self, image) -> str:
        """Tesseract'ı tek bir sayfa görüntüsü üzerinde çalıştır.

        Args:
            image: Bir PIL görüntüsü.

        Returns:
            Tanınan metin.
        """
        config = f"--psm {self.page_segmentation_mode}"
        return pytesseract.image_to_string(image, lang=self.language, config=config)

    def supports(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> bool:
        """PDF'leri ve raster görüntüleri kabul et; metinsel her şeyi reddet."""
        if has_pdf_magic_bytes(content) or mime_type == "application/pdf":
            return True
        if mime_type and mime_type.startswith("image/"):
            return True
        return matches_extension(file_name, IMAGE_EXTENSIONS | PDF_EXTENSIONS)
