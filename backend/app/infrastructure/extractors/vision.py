import asyncio
import base64
import io
import json
import logging
import urllib.request
from abc import abstractmethod
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

try:  # pragma: no cover - testlerde patch ile çalıştırılır
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
#: Transkripsiyon talimatı, bilinçli olarak İngilizce.
#:
#: Bu daha önce Türkçe "Bu belgedeki tüm metni olduğu gibi, satır yapısını
#: koruyarak çıkar." idi. Bir modele Türkçeyi Türkçe olarak okumasını istemek
#: bariz biçimde doğru görünür ve o dönemde sevk edilen dahil, denenen her
#: model için en kötü seçenek olarak ölçüldü: glm-ocr yalnızca Türkçe
#: ifadeyi bırakarak NED 0.164'ten 0.145'e düştü, deepseek-ocr ise tam bir
#: başarısızlıktan (NED 1.000, boş çıktı) en iyi sonucuna geçti. Talimat
#: dili transkripsiyon dili değildir -- bu modeller İngilizce talimatları
#: çok daha güvenilir biçimde takip eder ve transkribe ettikleri metin,
#: hangi dilde soruldukları konusundan etkilenmez.
#:
#: Bunu ve `settings.OLLAMA_VISION_MODEL`'i değiştirmek birbirine bağlıdır:
#: deepseek-ocr eski Türkçe prompt altında hiçbir şey döndürmüyor.
DEFAULT_PROMPT = "Extract all text from this document exactly as it appears."
#: Türkçe resmi yazışmanın tam bir sayfası için yeterince cömert. Ayarlanmazsa,
#: Ollama transkripsiyonu bir alan değerinin ortasında keser.
DEFAULT_NUM_PREDICT = 4096
DEFAULT_NUM_CTX = 8192
REQUEST_TIMEOUT_SECONDS = 300


class VisionExtractorBase(BaseDocumentExtractor):
    """Vision-model OCR için paylaşılan rasterizasyon/işaret tespit makinesi.

    Bir PDF/görüntüyü model girdisine çevirme ve sonucu bir
    `ExtractedDocument` olarak paketleme konusundaki her şey sağlayıcıdan
    bağımsızdır; yalnızca gerçek model çağrısı (`_transcribe`)
    `OllamaVisionExtractor` (yerel, Ollama'nın `/api/generate`'ine karşı
    ham HTTP) ile `EvrenVisionExtractor` (Evren'in OpenAI uyumlu chat
    completions'ı) arasında farklıdır.
    """

    def __init__(self, dpi: int = OCR_RENDER_DPI, prompt: str = DEFAULT_PROMPT) -> None:
        """Vision çıkarıcısını başlat.

        Args:
            dpi: PDF sayfaları için rasterizasyon yoğunluğu.
            prompt: Transkripsiyon talimatı.
        """
        self.dpi = dpi
        self.prompt = prompt

    @abstractmethod
    async def _transcribe(self, image: bytes) -> str:
        """Bir sayfa görüntüsünü modele gönder ve transkripsiyonunu döndür.

        Args:
            image: Tek bir sayfanın PNG byte'ları.

        Returns:
            Transkribe edilen metin.
        """

    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        raster_cache: Optional[dict] = None,
    ) -> ExtractedDocument:
        """Taranmış bir belgeyi görsel bir dil modeliyle transkribe et.

        Args:
            content: Ham PDF veya görüntü byte'ları.
            file_name: Girdi türüne karar vermek için kullanılan orijinal dosya adı.
            mime_type: Girdi türüne karar vermek için kullanılan bildirilen içerik türü.
            raster_cache: DPI'ya göre anahtarlanmış, zaten rasterize edilmiş
                sayfaların isteğe bağlı paylaşılan önbelleği (bkz.
                `BaseDocumentExtractor.extract`). Bu çıkarıcı genellikle
                `TesseractExtractor` bir sonucu reddettikten *sonraki*
                yükselme adımıdır, bu yüzden yaygın durum önbellek isabetidir
                -- aynı PDF'i ikinci kez rasterize etmek yerine aynı DPI'da
                zaten render edilmiş sayfaları yeniden kullanır.

        Returns:
            OCR çıktısı olarak işaretlenmiş, transkribe edilen metin.

        Raises:
            DocumentExtractionError: Rasterizasyon veya model çağrısı başarısız olursa.
        """
        is_pdf = has_pdf_magic_bytes(content) or mime_type == "application/pdf"
        if is_pdf and pdfium is None:
            raise DocumentExtractionError(
                "pypdfium2 kurulu değil; PDF görüntüye çevrilemedi."
            )

        try:
            if not is_pdf:
                images = [content]
                # Yalnızca aşağıdaki işaret tespiti için çözülür (kendi
                # try/except'ine bakın) -- yukarıdaki transkripsiyon çağrısı
                # bu dal için hiçbir zaman bir PIL nesnesine ihtiyaç
                # duymadı, bu yüzden burada bir çözme hatası transkripsiyonu
                # bozmamalı, bu yüzden bu, metodun geri kalanıyla aynı
                # try/except'e katılmıyor.
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
            # Bilinçli olarak sıralı, TesseractExtractor'ın sayfa döngüsünün
            # aksine. Tesseract sayfaları güvenle paralelleşir çünkü her OCR
            # çağrısı, işletim sisteminin zaten zamanladığı çekirdekler için
            # yarışan kendi `tesseract` alt sürecidir. Bir vision-model
            # çağrısı ise sunulan tek bir modele karşı bir üretim isteğidir;
            # yerel Ollama, verilen bir modele karşı üretimi eşzamanlı
            # istekler yerine sıralar, bu yüzden eşzamanlı sayfa istekleri,
            # istemci tarafındaki dağılımdan bağımsız olarak sunucu
            # tarafında birbirinin arkasında kuyruğa girer -- bu proje aynı
            # model için eşzamanlı sınıflandır+çıkar çağrılarında zaten net
            # bir kayıp olarak ölçtüğü aynı maliyet şekli. Bunu yalnızca
            # canlı ölçümlerle karşılaştırarak yeniden gözden geçirin;
            # burada yanlış tahmin etmek, zaten okunması en zor belgeler
            # için son çare yol olan bu çıkarıcıya özel olarak gecikme
            # maliyeti getirir.
            pages = [await self._transcribe(img) for img in images]
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError(
                f"Görsel dil modeli ile OCR başarısız oldu: {exc}"
            ) from exc

        text = "\n\n".join(pages).strip()
        logger.info(
            "%s (%s) transcribed %d page(s), %d characters.",
            self.name,
            getattr(self, "model", "?"),
            len(pages),
            len(text),
        )
        # En iyi çaba, aynı render edilmiş sayfalar: detect_marks asla
        # exception fırlatmaz (kendi docstring'ine bakın), bu yüzden
        # buradaki bir dedektör hatası aksi halde başarılı olan bir
        # transkripsiyonu asla başarısız kılmamalı.
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

    async def render_first_page(self, content: bytes) -> Optional["_PILImage.Image"]:
        """Bir PDF'in yalnızca 1. sayfasını başlık bandı onarımının kendi kullanımı için rasterize et.

        `_render_pages` her sayfayı render eder ve tam bir OCR geçişi zaten
        sürerken kullanılır; bu ise tam tersi durum için var -- başlık
        onarımı, hiçbir şey render etmemiş bir çıkarıcının sonucunun 1.
        sayfasına ihtiyaç duyar (bir metin katmanı yolu, örn. OpenDataLoader
        veya PdfiumExtractor bir Class-A tarayıcı metin katmanını okuyor --
        bkz. `FallbackDocumentExtractor.is_scanned_text_layer`). Yalnızca 1.
        sayfayı render etmek, onarımın yalnızca ilk sayfanın başlık bandına
        dokunması nedeniyle bu her zaman ödenen maliyeti belge uzunluğundan
        bağımsız olarak yaklaşık bir sayfa ile sınırlı tutar.

        Args:
            content: Ham PDF byte'ları.

        Returns:
            İlk sayfa, render edilmiş bir PIL görüntüsü olarak, ya da
            `content` render edilebilir bir PDF değilse (bozuk byte'lar,
            sayfa yok, veya pdfium kullanılamıyor) None -- çağıranlar bunu,
            exception fırlatmak yerine orijinal, onarılmamış metne
            düşülmesi gereken bir durum olarak ele almalıdır.
        """
        if pdfium is None:
            return None
        try:
            document = pdfium.PdfDocument(content)
        except Exception:
            return None

        try:
            if len(document) == 0:
                return None
            page = document[0]
            try:
                scale = self.dpi / PDF_POINTS_PER_INCH
                bitmap = page.render(scale=scale)
                return bitmap.to_pil()
            finally:
                page.close()
        except Exception:
            return None
        finally:
            document.close()

    def _render_pages(self, content: bytes) -> list:
        """Bir PDF'in her sayfasını belge sırasına göre PIL görüntüsüne rasterize et.

        PNG kodlamasından (`_encode_png`) ayrı tutulur, böylece
        `raster_cache`'e giren şey ham render edilmiş sayfalardır --
        `TesseractExtractor`'ın önbelleklediği aynı şekil, özellikle PNG
        byte'larına ihtiyaç duymayan herhangi bir gelecekteki tüketici için
        yeniden kullanılabilir.

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

    def _encode_png(self, images: list) -> list[bytes]:
        """PIL görüntülerini PNG byte'larına kodla.

        Args:
            images: Belge sırasına göre PIL görüntüleri.

        Returns:
            Aynı sırayla, görüntü başına PNG kodlu byte'lar.
        """
        encoded = []
        for image in images:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            encoded.append(buffer.getvalue())
        return encoded

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

    async def transcribe_header_band(self, page_image) -> str:
        """Zaten rasterize edilmiş bir sayfanın yalnızca başlık bandını transkribe et.

        Bu sınıfın kendi `extract()`'i tarafından değil,
        `FallbackDocumentExtractor`'ın başlık onarım adımı tarafından
        kullanılır. Sayfanın üst `HEADER_BAND_FRACTION`'ını kırpar ve
        yalnızca o kırpımı, tam sayfa transkripsiyonun kullandığı aynı model
        çağrısından geçirir -- küçük bir kırpım, bu projenin OCR zincirinin
        özellikle zorlandığı kısım (antetli kaşe amblemleri, el yazısı
        notlar) için tam sayfa maliyetinin bir kısmına mal olur, Tesseract'ın
        zaten iyi okuduğu gövde metni için bu maliyeti ödemeden.

        Args:
            page_image: `raster_cache`'ten gelen rasterize edilmiş bir PIL
                sayfa görüntüsü (bu sınıfın kendi `extract()`'i ile
                `TesseractExtractor`'ın aynı önbellek girdisini paylaştığı
                aynı şekil).

        Returns:
            Kırpımın transkripsiyonu. Gerçekten boş bir başlıkta boş
            olabilir; çağıranlar bunu diğer en-iyi-çaba başarısızlıkları
            gibi ele almalı, yeniden denememeli.

        Raises:
            DocumentExtractionError: Model çağrısının kendisi başarısız olursa.
        """
        width, height = page_image.size
        crop = page_image.crop((0, 0, width, int(height * HEADER_BAND_FRACTION)))
        try:
            encoded = await asyncio.to_thread(self._encode_png, [crop])
            return await self._transcribe(encoded[0])
        except Exception as exc:
            raise DocumentExtractionError(
                f"Görsel dil modeli ile başlık onarımı başarısız oldu: {exc}"
            ) from exc

    async def transcribe_page(self, page_image) -> str:
        """Zaten rasterize edilmiş bir sayfayı tamamen, kırpma olmadan transkribe et.

        `transcribe_header_band`'in kardeşi -- aynı model çağrısı, aynı
        `self.prompt`, yalnızca üst `HEADER_BAND_FRACTION` bandı yerine
        tüm sayfa. `FallbackDocumentExtractor`'ın imza kurtarma adımı
        tarafından (bkz. o sınıfın `_repair_signature`'ı) başlık bandı
        onarımının ulaşamadığı başarısızlık modu için kullanılır: ıslak
        imza mürekkebinin altındaki basılı ismi gizlemesi, başlık bandının
        çok ötesinde, sayfanın alt yarısında yer alır. Doğrudan
        OpenDataLoader/Tesseract'ın imza sahibinin adını tamamen kaybettiği
        veya bozduğu dört gerçek belge üzerinde ölçüldü (eksik bir satır,
        veya "Bekir BOZDAĞ" için "İF; BOZDAG ;") -- tam sayfa
        transkripsiyon dördünde de doğru ismi kurtardı.

        Sağlayıcıya özel bir alt sınıfta değil, temel sınıfta yaşar: gövde
        yalnızca `_encode_png`/`_transcribe`'i çağırır, ikisi de burada
        zaten sağlayıcıdan bağımsızdır, bu yüzden her `VisionExtractorBase`
        alt sınıfı tam sayfa kurtarmayı bedavaya alır.

        Args:
            page_image: `transcribe_header_band` ve `TesseractExtractor`'ın
                bir `raster_cache` girdisini paylaştığı aynı şekilde
                rasterize edilmiş bir PIL sayfa görüntüsü.

        Returns:
            Sayfanın tam transkripsiyonu. Tam başarısızlıkta boş olabilir;
            çağıranlar bunu diğer en-iyi-çaba başarısızlıkları gibi ele
            almalı, yeniden denememeli.

        Raises:
            DocumentExtractionError: Model çağrısının kendisi başarısız olursa.
        """
        try:
            encoded = await asyncio.to_thread(self._encode_png, [page_image])
            return await self._transcribe(encoded[0])
        except Exception as exc:
            raise DocumentExtractionError(
                f"Görsel dil modeli ile tam sayfa okuma başarısız oldu: {exc}"
            ) from exc



class OllamaVisionExtractor(VisionExtractorBase):
    """Ollama tarafından sunulan yerel bir görsel dil modeliyle OCR.

    `TesseractExtractor`'ın yerini almak yerine onu tamamlar. Bu projenin
    korpusunda ölçüldüğünde, Tesseract temiz 300 DPI render'larda hem daha
    doğru hem de kabaca yetmiş kat daha hızlıdır. Bozuk taramalarda --
    eğik, bulanık, düşük kontrastlı, JPEG sıkıştırmalı, bir evrakın gerçekte
    fotokopi çekilmiş veya fotoğraflanmış haliyle geldiği şekilde --
    Tesseract çöker; örnek korpustaki 62 başlık alanından yalnızca **1**'ini
    kurtarırken bu model 58'ini kurtarır.

    Bu yüzden zincir hız için önce Tesseract'ı tutar ve yalnızca sonuç
    okunabilirlik kontrolünü geçemediğinde buraya yükselir.

    Model seçimi hakkında (bkz. `scripts/evaluate_ocr_fields.py`): adaylar
    metnin ne kadar iyi okunduğuna göre değil, kaç öngörülen alanın hayatta
    kaldığına göre değerlendirilir ve ikisi keskin biçimde ayrışır. 62
    etiketli alan taşıyan 12 bozuk evrak üzerinde:

    ==========================  ==========  ==========  ============
    model                       bulunan     tam         OCRTurk tokF1
    ==========================  ==========  ==========  ============
    tesseract                   1/62        0/62        0.411
    glm-ocr                     59/62       35/62       0.676
    deepseek-ocr (mevcut)       58/62       48/62       0.846
    frob/unlimited-ocr:q8_0     0/62        0/62        0.708
    ==========================  ==========  ==========  ============

    `frob/unlimited-ocr` bu alan metriğinin neden var olduğunu gösterir.
    Metin sadakatinde glm-ocr'ı geçer ama **sıfır** alan kurtarır -- Türkçeyi
    doğru okur ama sayfayı yeniden biçimlendirir, ve ayrıştırıcının
    bulamadığı bir başlık eksik bilgi olarak raporlanır. Metin metrikleri bu
    başarısızlığı göremez.

    glm-ocr ve deepseek-ocr aynı alanları bulur (59'a karşı 58, belge belge
    kazanıp kaybederek -- bu örneklem büyüklüğünde gürültü). *Değerin*
    doğru olup olmadığı konusunda ayrışırlar, ve orada deepseek-ocr kesin
    biçimde öndedir: 48'e karşı 35 tam eşleşme. Aynı eksik-alan doğruluğu,
    çok daha az yanlış değer, ve yukarıdaki sentetik korpusta daha hızlı --
    bu da orijinal varsayılanı belirledi.

    O sentetik korpus (12 belge, bir bozulma profili) gerçek taramalar
    karşısında tutarlı çıkmadı. `scripts/evaluate_ocr_real.py`'nin 19
    elle etiketlenmiş gerçek `CY-*.pdf` belgesi (76 alan,
    `datasets/resmi_yazisma/ocr_ground_truth.json`) üzerinde, ham tam sayfa
    transkripsiyon yerine gerçek üretim zincirinden (Tesseract + başlık
    bandı onarımı) geçirilerek yeniden ölçüldü:

    ======================  ===========  ===========  =====
    motor                   zincir bul.  zincir tam   süre
    ======================  ===========  ===========  =====
    tesseract               64/76        32/76         54s
    deepseek-ocr (eski)     65/76        42/76        730s
    glm-ocr:latest (yeni)   67/76        50/76       1579s
    ======================  ===========  ===========  =====

    glm-ocr:latest daha fazla alan kurtarır ve daha fazlasını tam doğru
    yapar -- tam eşleşmede kabaca %19 göreli kazanım -- kabaca iki kat
    duvar saati süresi pahasına. Bu takas bilinçli olarak doğruluk lehine
    yapıldı: bu projenin uyum kontrolcüsü yanlış bir değeri doğruymuş gibi
    raporlar, bu ise bir alanı eksik olarak raporlamaktan daha kötüdür.

    Bu ayrıca o araştırma sırasında ortaya çıkan belirli bir soruyu da
    çözdü: *aynı* GLM-OCR ağırlıklarının (`zai-org/GLM-OCR`, bkz.
    `scripts/ocr_sidecar.py`) bir torch/transformers dağıtımı, bu
    Ollama-sunulan sürümü **geçmiyor** -- karşılaştırma altyapısındaki
    gerçek bir hata düzeltildikten sonra 46/76'ya karşı 50/76 tam eşleşme
    (modele indirgenmemiş 300 DPI bir sayfa besleniyordu; girdi
    çözünürlüğünü sınırlamak -- bkz. `ocr_sidecar.MAX_IMAGE_DIMENSION` --
    bunu düzeltti ve daha önceki, yanlış "transformers çok daha hızlı"
    okumasını tersine çevirdi, ama doğruluk farkını kapatmadı). Sonuç
    olarak hiçbir transformers dağıtımı sevk edilmiyor: Ollama-sunulan
    model zaten kazanıyor.

    Ayrı bir bulgu, yukarıdaki tablo bu modeli varsayılan olarak sevk
    ettikten sonra: bu çıkarıcının *kendi* tam sayfa transkripsiyonu
    üretimde neredeyse hiç çalışmadı. `FallbackDocumentExtractor` yalnızca
    `char_count`/`quality_ratio`'yu geçen ilk sonuçta durdu, ve o belge
    geneli okunabilirlik ortalaması başlık hasarını göremez -- gerçek bir
    belge 0.85 quality_ratio ve 3316 karakter skorlarken beş öngörülen
    başlık alanından **sıfırını** kurtarmıştı. Bunu düzelten alan-farkında
    kabul kriteri için `FallbackDocumentExtractor
    ._has_enough_header_fields`'e, ve başlık bandı onarımını bir
    tarayıcının kendi çöp OCR metin katmanına genişleten eşlik eden
    düzeltme için `is_scanned_text_layer`'a bakın (önceden `used_ocr`
    kapısına görünmezdi). Her iki düzeltme yerindeyken, büyümüş 23 belgelik
    ground truth (88 alan, bu başarısızlığı vurduğu için özel olarak
    eklenen 4 belge) üzerinde, gerçek üretim zincirinden geçirilerek
    yeniden ölçüldü:

    ======================  ===========  ===========  =======
    motor                   zincir bul.  zincir tam    süre
    ======================  ===========  ===========  =======
    tesseract               74/88        36/88          71s
    glm-ocr:latest          77/88        59/88        2110s
    ======================  ===========  ===========  =======

    Orijinal 19 belge/76 alanlık alt küme her iki motor altında da tam
    olarak sabit kalır (64/76 ve 68/76 bulunan, yukarıdaki tabloyla byte
    eşit) -- yeni kriter zaten doğru kabul edilmiş bir belge için hiçbir
    şey değiştirmiyor. CY-034, `OpenDataLoaderExtractor`'daki markdown
    başlık kırpmasından bir tam eşleşme kazandı (0 -> 1). Eklenen 4
    belgenin en kötü durumu (CY-050: eski kural altında 3 kurtarılabilir
    alanın 0'ı, bu düzeltmeden önce doğrudan canlı önbelleğe karşı
    doğrulandı) şimdi her iki motorun zincirinde de 3'ünün tamamını
    kurtarıyor -- yeni kriterin yakalamak için var olduğu tam olarak o
    belgeler yükseldi, ve yalnızca onlar: tüm çalışma boyunca 23 belgeden
    2'si alan-tetiklemeli yükselmeyi tetikledi.
    """

    name = "ollama_vision"

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        dpi: int = OCR_RENDER_DPI,
        prompt: str = DEFAULT_PROMPT,
    ) -> None:
        """Vision çıkarıcısını başlat.

        Args:
            model: Ollama vision model etiketi; varsayılan `settings.OLLAMA_VISION_MODEL`.
            base_url: Ollama uç noktası; varsayılan `settings.OLLAMA_BASE_URL`.
            dpi: PDF sayfaları için rasterizasyon yoğunluğu.
            prompt: Türkçe transkripsiyon talimatı.
        """
        super().__init__(dpi=dpi, prompt=prompt)
        self.model = model or settings.OLLAMA_VISION_MODEL
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")

    async def _transcribe(self, image: bytes) -> str:
        """Bir sayfa görüntüsünü Ollama'nın ham `/api/generate`'ine gönder ve transkripsiyonunu döndür.

        Args:
            image: Tek bir sayfanın PNG byte'ları.

        Returns:
            Transkribe edilen metin.
        """

        def _call() -> str:
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

        return await asyncio.to_thread(_call)


class EvrenVisionExtractor(VisionExtractorBase):
    """Evren'in hızlı katmanı üzerinden, çok modlu bir chat completion olarak gönderilen OCR.

    Evren'in kendi `vlm` model takma adı yalnızca video içindir -- görüntü
    taşıyan herhangi bir isteği 400 ile reddeder ("At most 0 image(s) may be
    provided"). Evren'in kendi sorun giderme dokümanları OCR/belge
    görüntülerini bunun yerine `llm-fast` veya `llm-large`'a yönlendirmeyi
    önerir (istek başına en fazla 2 görüntü; bu çıkarıcı her seferinde
    yalnızca bir sayfa gönderir). `settings.LOCAL_MODE` False olduğunda
    onun yerine kullanılan `OllamaVisionExtractor` ile aynı yükselme rolüne
    sahiptir, bkz. `app.infrastructure.extractors.get_document_extractor`
    ve `app.api.dependency`.
    """

    name = "evren_vision"

    def __init__(
        self,
        model: Optional[str] = None,
        dpi: int = OCR_RENDER_DPI,
        prompt: str = DEFAULT_PROMPT,
    ) -> None:
        """Vision çıkarıcısını başlat.

        Args:
            model: Evren model takma adı; varsayılan `settings.EVREN_LLM_FAST_MODEL`.
            dpi: PDF sayfaları için rasterizasyon yoğunluğu.
            prompt: Transkripsiyon talimatı.
        """
        super().__init__(dpi=dpi, prompt=prompt)
        self.model = model or settings.EVREN_LLM_FAST_MODEL

    async def _transcribe(self, image: bytes) -> str:
        """Bir sayfa görüntüsünü Evren'e çok modlu bir chat mesajı olarak gönder.

        Args:
            image: Tek bir sayfanın PNG byte'ları.

        Returns:
            Transkribe edilen metin.
        """
        from app.ai.llms import get_llm_client

        client = get_llm_client(
            provider="evren",
            model=self.model,
            temperature=0.0,
            max_tokens=DEFAULT_NUM_PREDICT,
        )
        encoded = base64.b64encode(image).decode()
        return await client.generate(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{encoded}"},
                        },
                    ],
                }
            ],
            temperature=0.0,
            max_tokens=DEFAULT_NUM_PREDICT,
        )
