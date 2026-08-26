import re
from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field

from app.core.constants import (
    FULL_PAGE_IMAGE_MIN_COVERAGE,
    TEXT_LAYER_PROBE_MAX_PAGES,
    TEXT_LAYER_PROBE_MIN_CHARS,
)
from app.infrastructure.extractors.marks import DetectedMark

try:  # pragma: no cover - testlerde patch ile çalıştırılır
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None

PDF_MAGIC_BYTES = b"%PDF"

#: Kelime-benzeri jeton: harf ve rakamlar, Türkçe karakterler dahil.
_TOKEN_PATTERN = re.compile(r"[0-9A-Za-zÇĞİÖŞÜçğıöşü]+")
#: Bu uzunlukta veya daha uzun jetonlar OCR gürültüsü değil gerçek kelime kabul edilir.
_WORD_MIN_LENGTH = 3


class DocumentExtractionError(Exception):
    """Bir belgenin metni çıkarılamadığında fırlatılır.

    Bilinçli olarak `app.api.exceptions` alt sınıfı yerine düz bir exception --
    böylece infrastructure katmanı HTTP katmanından bağımsız kalır. Bunu bir API
    exception'ına çevirmek domain servisinin sorumluluğundadır.
    """


class ExtractedDocument(BaseModel):
    """Ham yüklenen byte'lardan ayrıştırılan bir belgenin metni ve kaynağı."""

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
    detected_marks: list[DetectedMark] = Field(
        default_factory=list,
        description=(
            "Taranmış sayfalarda tespit edilen olası imza/mühür/el yazısı "
            "bölgeleri. Yalnızca OCR yolundaki çıkarıcılar doldurur "
            "(TesseractExtractor, OllamaVisionExtractor) -- doğrudan metin "
            "katmanı okunan belgeler sayfa hiç görüntüye çevrilmediğinden "
            "boş liste döner. Bir inceleme ipucudur, adli tespit değildir."
        ),
    )

    @property
    def char_count(self) -> int:
        """Çıkarılan metindeki, baştaki/sondaki boşluklar kırpılmış karakter sayısı."""
        return len(self.text.strip())

    @property
    def quality_ratio(self) -> float:
        """OCR gürültüsü değil gerçek kelime sayılacak kadar uzun jetonların oranı.

        Yalnızca karakter sayısı iyi bir sonucu kötüden ayırt edemez: bozuk bir
        taramada çalıştırılan OCR, herhangi bir uzunluk eşiğini geçen yüzlerce
        karakterlik anlamsız metni mutlulukla döndürür. Başarısız tanıma metni
        bir-iki karakterlik parçalara böler, bu yüzden kelime uzunluğundaki
        jetonların payı ikisini net biçimde ayırır -- bu projenin korpusunda
        ölçüldüğünde, okunabilir Türkçe yaklaşık 0.80, kullanılamaz çıktı ise
        yaklaşık 0.39 skorlar.

        Returns:
            0.0 ile 1.0 arası oran; hiç metin yoksa 0.0.
        """
        tokens = _TOKEN_PATTERN.findall(self.text)
        if not tokens:
            return 0.0
        readable = [token for token in tokens if len(token) >= _WORD_MIN_LENGTH]
        return len(readable) / len(tokens)


class BaseDocumentExtractor(ABC):
    """Ham belge byte'larını `ExtractedDocument`'e çeviren soyut metin çıkarıcı.

    Bilinçli olarak yol yerine byte alır: her iki çağıran da zaten byte tutar
    (`UploadFile.read()` ve `BaseStorage.get_file()`), S3 storage backend'inin
    ise hiç yerel yolu yoktur. Yol tabanlı veya dosya tabanlı bir aracı saran
    adaptörler kendi geçici dosyalarından kendileri sorumludur.
    """

    #: `ExtractedDocument.extractor` içinde kaydedilen kısa tanımlayıcı.
    name: str = "base"

    @abstractmethod
    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        raster_cache: Optional[dict] = None,
    ) -> ExtractedDocument:
        """Ham belge byte'larından metin çıkar.

        Args:
            content: Ham belge byte'ları.
            file_name: Uzantı bazlı yönlendirme için kullanılan orijinal dosya adı.
            mime_type: Yönlendirme için kullanılan bildirilen içerik türü.
            raster_cache: Bu tek belge için DPI'ya göre anahtarlanmış, zaten
                rasterize edilmiş PDF sayfalarının isteğe bağlı paylaşılan
                önbelleği. Taranmış bir PDF, `FallbackDocumentExtractor`'ın
                önce denediği hangi OCR çıkarıcıysa onun tarafından render
                edilir; o sonuç reddedilip zincir bir sonraki OCR çıkarıcıya
                yükseldiğinde, bu önbellek pdfium'un render maliyetini tekrar
                ödemeden aynı render edilmiş sayfaların yeniden kullanılmasını
                sağlar. `FallbackDocumentExtractor` her üst düzey `extract()`
                çağrısı için bir tane oluşturur ve aşağı aktarır; hiç
                rasterize etmeyen çıkarıcılar (`PlainTextExtractor`,
                `OpenDataLoaderExtractor`) bunu yok sayar.

        Returns:
            Sayfa dökümü ve kaynak bilgisiyle birlikte çıkarılan metin.

        Raises:
            DocumentExtractionError: Bu çıkarıcı girdiyi ayrıştıramazsa.
        """

    def supports(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> bool:
        """Bu çıkarıcının verilen girdi için denenip denenmeyeceğini bildirir.

        Zinciri korumak önemlidir: bu olmadan düz metin çıkarıcı, PDF
        byte'larını büyük bir replacement-character bloğuna çözer, minimum
        karakter eşiğini geçer ve aslında onu okuyabilecek çıkarıcının önüne
        geçebilir.

        Args:
            content: Ham belge byte'ları.
            file_name: Orijinal dosya adı.
            mime_type: Bildirilen içerik türü.

        Returns:
            Bu çıkarıcı girdiye uygulanabilirse True.
        """
        return True


def has_pdf_magic_bytes(content: bytes) -> bool:
    """Buffer'ın PDF dosya imzasıyla başlayıp başlamadığını bildirir.

    Args:
        content: Ham belge byte'ları.

    Returns:
        Bildirilen MIME türünden bağımsız olarak içerik bir PDF ise True.
    """
    return content[:4] == PDF_MAGIC_BYTES


def has_pdf_text_layer(content: bytes) -> bool:
    """Bir PDF'in anlamlı bir gömülü metin katmanı olup olmadığını ucuz biçimde bildirir.

    pdfium'un yerel metin akışını doğrudan okur -- OCR yok, JVM yok -- bu
    yüzden `OpenDataLoaderExtractor` ya da `PdfiumExtractor`'ın denemeye
    değip değmediğine karar vermeden önce çalıştırılacak kadar hızlıdır.
    Gerçek bir taramanın hiçbir sayfasında metin katmanı yoktur; dijital
    doğan bir PDF'in ise neredeyse anında gerçek metni vardır, bu yüzden ilk
    birkaç sayfayı kontrol etmek uzun bir belgede bile ikisini ucuza ayırt eder.

    Args:
        content: Ham PDF byte'ları.

    Returns:
        pdfium yeterince gömülü metin bulursa, ya da sondanın kendisi hiç
        çalışamazsa (pdfium eksik, veya PDF açılamıyor) True. Açık başarısız
        olmak bilinçlidir: bu fonksiyon sadece bir taramada zaman
        harcayacak çıkarıcıları atlamak için var, ve dosyayı açamayan bir
        sonda, sessiz bir atlamadan çok "gerçek çıkarıcılar hatayı bildirsin"
        olarak çok daha bilgilendiricidir.
    """
    if pdfium is None:
        return True
    try:
        document = pdfium.PdfDocument(content)
    except Exception:
        return True

    try:
        found = 0
        for index, page in enumerate(document):
            if index >= TEXT_LAYER_PROBE_MAX_PAGES:
                break
            text_page = page.get_textpage()
            try:
                found += len(text_page.get_text_range().strip())
            finally:
                text_page.close()
                page.close()
        return found >= TEXT_LAYER_PROBE_MIN_CHARS
    except Exception:
        return True
    finally:
        document.close()


def has_full_page_image(content: bytes) -> bool:
    """Bir PDF'in ilk sayfasının tek bir gömülü görüntüye hakim olup olmadığını bildirir.

    Gerçekten dijital doğan bir sayfayı, yalnızca bir tarayıcının kendi gömülü
    OCR geçişinin orijinal taramanın tam sayfa bir rasterinin üzerine metin
    katmanı yazdığı için metin katmanı *taşıyan* bir sayfadan ("Class A" --
    bkz. `is_scanned_text_layer`) ayırt eden discriminator'ın ikinci yarısı.
    `has_pdf_text_layer` tek başına ikisini ayıramaz; ikisi de gerçek metin
    bildirir. Bu projenin kendi korpusundaki 86 gerçek PDF ve canlı
    yüklemeler üzerinde ölçüldüğünde, bu sonda her Class-A/taranmış sayfa
    için en büyük görüntü kapsamasını tam olarak 1.0, gerçekten dijital doğan
    her sayfa için ise tam olarak 0.0 olarak bulur -- hiçbir belge ikisi
    arasına düşmez, bu yüzden `FULL_PAGE_IMAGE_MIN_COVERAGE`'ın ince
    kalibrasyona ihtiyacı olmadı.

    Args:
        content: Ham PDF byte'ları.

    Returns:
        1. sayfadaki en büyük gömülü görüntü nesnesi sayfa alanının en az
        `FULL_PAGE_IMAGE_MIN_COVERAGE`'ını kaplıyorsa True. Sonda hiç
        çalışamıyorsa -- pdfium eksik, PDF açılmıyor, ya da hiç sayfası
        yoksa -- False. Bu, `has_pdf_text_layer`'ın açık başarısız olma
        davranışının tersidir: o sonda çıkarıcıları *atlamak* için var,
        bu yüzden açık başarısız olmak sadece "gerçek çıkarıcı hatayı
        bildirsin" demektir. Bu sonda ise (bkz. `is_scanned_text_layer`'ın
        tek çağıranı, `FallbackDocumentExtractor._maybe_repair_header`)
        OCR'a değer olarak neyin sayıldığını *genişletir*, bu yüzden kapalı
        başarısız olmak, bu sondanın inceleyemediği bir dosyanın fazladan
        vision modeli bütçesini asla harcamaması anlamına gelir.
    """
    if pdfium is None:
        return False
    try:
        document = pdfium.PdfDocument(content)
    except Exception:
        return False

    try:
        if len(document) == 0:
            return False
        page = document[0]
        try:
            width, height = page.get_width(), page.get_height()
            if not width or not height:
                return False
            page_area = width * height
            coverage = 0.0
            for obj in page.get_objects():
                if obj.type != pdfium.raw.FPDF_PAGEOBJ_IMAGE:
                    continue
                left, bottom, right, top = obj.get_bounds()
                coverage = max(
                    coverage, abs((right - left) * (top - bottom)) / page_area
                )
            return coverage >= FULL_PAGE_IMAGE_MIN_COVERAGE
        finally:
            page.close()
    except Exception:
        return False
    finally:
        document.close()


def is_scanned_text_layer(content: bytes) -> bool:
    """Bir PDF'in gömülü metin katmanının tarayıcı kaynaklı çöp olup olmadığını bildirir.

    Class-A discriminator'ının her iki yarısını birleştirir: tam sayfa bir
    rasterin (`has_full_page_image`) üzerine oturan gerçek bir metin katmanı
    (`has_pdf_text_layer`). Sinyallerden yalnızca biri yetersizdir -- tam
    sayfa görüntüsü olmayan gerçek bir metin katmanı sıradan dijital doğan
    bir PDF'dir, metin katmanı olmayan tam sayfa görüntü ise hiç OCR metni
    olmayan gerçek bir tarama (zaten `has_pdf_text_layer`'ın kendi başına
    False dönmesiyle OCR çıkarıcılarına yönlendirilmiştir).

    Args:
        content: Ham PDF byte'ları.

    Returns:
        Yalnızca her iki sinyal de sayfanın tam sayfa bir tarama görüntüsü
        üzerinde tarayıcı kaynaklı metin taşıdığında hemfikir olursa True.
    """
    return has_pdf_text_layer(content) and has_full_page_image(content)


def matches_extension(file_name: Optional[str], extensions: set[str]) -> bool:
    """Bir dosya adının verilen uzantılardan biriyle bitip bitmediğini bildirir.

    Args:
        file_name: İncelenecek dosya adı; None olabilir.
        extensions: Baştaki nokta olmadan küçük harfli uzantılar.

    Returns:
        Dosya adı uzantılardan birini taşıyorsa True.
    """
    if not file_name or "." not in file_name:
        return False
    return file_name.rsplit(".", 1)[1].lower() in extensions
