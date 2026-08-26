import asyncio
import contextlib
import logging
import os
import re
import tempfile
from typing import Iterator, Optional

from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
    has_pdf_magic_bytes,
    has_pdf_text_layer,
    matches_extension,
)

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised via patching in tests
    from langchain_opendataloader_pdf import OpenDataLoaderPDFLoader
except ImportError:  # pragma: no cover
    OpenDataLoaderPDFLoader = None

PDF_EXTENSIONS = {"pdf"}

#: Bir satırın başındaki öncü ATX başlık işaretini ("#" ile "######" arası,
#: ardından boşluk) eşleştirir ve başka hiçbir şeyi -- tablo çubukları ve
#: gövde metni içindeki bir '#' dokunulmadan bırakılır.
#:
#: `output_format="markdown"`, bu sözdizimini sıradan başlık satırlarına
#: enjekte eder (gözlemlenen: gerçek CY-034/ANKARA_BSB belgelerinde
#: "##### TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA" ve "### Konu : Soru
#: Önergesi"), ve bu daha sonra ayrıştırılmış bir alan değerine olduğu
#: gibi sızar -- parser'ın kendi çapaları (`(?:^|\n)\s*Konu`) da bu
#: işareti geçemez, bu yüzden başlık önekli bir satır bir alanın hiç
#: ayrıştırılmamasına sessizce sebep olabilir. Bu, belgenin bir özelliği
#: değil, bu extractor'ın kendi biçimlendirme seçimidir, bu yüzden
#: parser'da değil burada temizlenir -- metni her downstream tüketicisi
#: (parser, sınıflandırıcı prompt'u, Soru-Cevap parçalama, ayrıntılı özet,
#: metin görünümü arayüzü) için bir kez temizlemek, bir kişi veya başka
#: bir modelin ilk okuduğu sürümde '#' işaretlerini görünür bırakmak
#: yerine tercih edilir.
_MARKDOWN_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE)


@contextlib.contextmanager
def _temporary_pdf_path(content: bytes) -> Iterator[str]:
    """PDF byte'larını geçici bir dizin içinde diske yazar.

    OpenDataLoader, gerçek bir dosya gerektiren ve yanına kardeş çıktı
    dosyaları yazabilen bir Java CLI'ını sarar. Girdiyi ve her türlü
    çıktıyı tek bir `TemporaryDirectory` içinde tutmak, temizliği hiçbir
    ek takip gerektirmeyen tek bir işlem haline getirir.

    Args:
        content: Ham PDF byte'ları.

    Yields:
        Yazılan PDF dosyasının mutlak yolu.
    """
    with tempfile.TemporaryDirectory(prefix="odl_") as work_dir:
        pdf_path = os.path.join(work_dir, "input.pdf")
        with open(pdf_path, "wb") as handle:
            handle.write(content)
        yield pdf_path


class OpenDataLoaderExtractor(BaseDocumentExtractor):
    """OpenDataLoader PDF (Apache-2.0) tabanlı, yerleşim düzenine duyarlı PDF extractor'ı.

    Doğuştan dijital PDF'ler için tercih edilen extractor'dır, çünkü çok
    sütunlu yerleşimler için okuma sırasını geri kazanır, tablo yapısını
    korur ve başlıkları çıkarır; bunların hepsi resmi bir belgenin başlık
    bloğunu bulmaya yardımcı olur. PATH üzerinde Java 11+ çalışma zamanı
    gerektirir; Java veya paket yoksa zincir saf-Python extractor'lara
    düşer.
    """

    name = "opendataloader"

    def __init__(self, output_format: str = "markdown") -> None:
        """Extractor'ı başlatır.

        Args:
            output_format: OpenDataLoader çıktı biçimi; "markdown" başlık
                ve tabloları korur, "text" düz bir transkript üretir.
        """
        self.output_format = output_format

    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        raster_cache: Optional[dict] = None,
    ) -> ExtractedDocument:
        """OpenDataLoader kullanarak bir PDF'i sayfa başına metne ayrıştırır.

        Args:
            content: Ham PDF byte'ları.
            file_name: Orijinal dosya adı (kullanılmıyor).
            mime_type: Bildirilen içerik türü (kullanılmıyor).
            raster_cache: Kullanılmıyor; bu extractor PDF'in kendi metin
                katmanını okur ve hiçbir şeyi rasterize etmez.

        Returns:
            Sayfa başına bir girdi içeren çıkarılmış metin.

        Raises:
            DocumentExtractionError: Paket kullanılamıyorsa veya ayrıştırma başarısız olursa.
        """
        if OpenDataLoaderPDFLoader is None:
            raise DocumentExtractionError(
                "OpenDataLoader PDF kütüphanesi kurulu değil; PDF metni çıkarılamadı."
            )

        try:
            pages = await asyncio.to_thread(self._load_pages, content)
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError(
                f"OpenDataLoader ile PDF okunamadı: {exc}"
            ) from exc

        text = "\n\n".join(pages).strip()
        logger.info(
            "OpenDataLoaderExtractor parsed %d page(s), %d characters.",
            len(pages),
            len(text),
        )
        return ExtractedDocument(
            text=text,
            pages=pages,
            page_count=len(pages),
            extractor=self.name,
            used_ocr=False,
        )

    def _load_pages(self, content: bytes) -> list[str]:
        """Bloklayan loader'ı geçici bir dosyaya karşı çalıştırır ve sayfa metnini toplar.

        Args:
            content: Ham PDF byte'ları.

        Returns:
            Belge sırasına göre sayfa metni.
        """
        with _temporary_pdf_path(content) as pdf_path:
            loader = OpenDataLoaderPDFLoader(
                file_path=pdf_path,
                format=self.output_format,
                split_pages=True,
                # Resmi bir belge başlığındaki satır yapısı anlamsal olarak
                # kritiktir: "Sayı" ve "Tarih" aynı satırı paylaşır, "Konu"
                # altına yerleşir ve imza bloğu isim-sonra-unvan şeklindedir.
                # Varsayılan birleştirmede, alan çıkarma tarih/konu'yu
                # tamamen kaçırır ve imzalayanı ilgisiz alanlara yanlış
                # atar.
                keep_line_breaks=True,
                quiet=True,
            )
            documents = loader.load()
        return [
            _MARKDOWN_HEADING.sub("", document.page_content) for document in documents
        ]

    def supports(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> bool:
        """Metin katmanı olan PDF'leri kabul eder; gerçek taramaları doğrudan reddeder.

        Taranmış bir PDF'te bu extractor'ın bulacağı hiçbir şey yoktur --
        her zaman reddeder, ancak bunu öğrenmeden önce OpenDataLoader'ın
        JVM başlatma maliyetini ödemeden. `has_pdf_text_layer`, bunu önceden
        yakalayan, JVM gerektirmeyen ucuz bir sondadır; böylece bir tarama
        bunun yerine doğrudan OCR extractor'larına geçer.
        """
        is_pdf = (
            has_pdf_magic_bytes(content)
            or mime_type == "application/pdf"
            or matches_extension(file_name, PDF_EXTENSIONS)
        )
        return is_pdf and has_pdf_text_layer(content)
