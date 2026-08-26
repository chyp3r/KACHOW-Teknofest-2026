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
from app.infrastructure.extractors.vision import VisionExtractorBase

logger = logging.getLogger(__name__)

#: `_maybe_repair_header`'ın her `extract()` çağrısına özel `repair_cache`'i
#: altında transkribe edilen başlık metnini önbelleklediği sabit anahtar.
#: (`raster_cache`'in sözleşmesinin aksine) `header_repair.dpi` değil düz bir
#: sabit -- bu önbellek DPI'ya göre anahtarlanmış sayfa görüntüleri değil,
#: tam olarak tek bir şey (kırpım transkripsiyonu) tutar, bu yüzden DPI'yı
#: bu çağrı içinde hiç değişmeyen bir şey için anahtar olarak yeniden
#: kullanmaktan daha açıklayıcı bir dize kullanmak daha nettir.
_REPAIR_TEXT_CACHE_KEY = "header_text"
#: `_repair_full_page`'in tam sayfa transkripsiyonu için
#: `_REPAIR_TEXT_CACHE_KEY` ile aynı rol -- aynı `repair_cache` sözlüğünde
#: farklı bir anahtar, `_REPAIR_TEXT_CACHE_KEY`'den bağımsız olarak
#: doldurulur: kırpım bu tetiklendiğinde zaten çalışmış ve atılmış olabilir
#: (bkz. `_maybe_repair_page_one`), ikisi arasında yalnızca bir belgenin
#: sonunda sahip olduğu *nihai* metin karşılıklı dışlayıcıdır, her iki
#: vision çağrısının da gerçekleşip gerçekleşmediği değil.
_REPAIR_PAGE_CACHE_KEY = "full_page_text"


class FallbackDocumentExtractor(BaseDocumentExtractor):
    """Biri yeterli metin döndürene kadar sıralı bir çıkarıcı zinciri dener.

    Çıkarma *politikasının* -- hangi ayrıştırıcının denenecği, bir sonucun
    ne zaman güvenilemeyecek kadar zayıf olduğu, ne zaman OCR'a yükselineceği
    -- tek, test edilebilir bir yerde yaşaması için var; domain servisine
    dağılması yerine. Servis yalnızca `BaseDocumentExtractor`'a bağımlıdır ve
    bir zincirin var olduğunu hiç öğrenmez.
    """

    name = "fallback"

    def __init__(
        self,
        extractors: list[BaseDocumentExtractor],
        min_char_count: int = MIN_EXTRACTED_CHAR_COUNT,
        min_quality_ratio: float = MIN_TEXT_QUALITY_RATIO,
        header_repair: Optional[VisionExtractorBase] = None,
        header_field_probe: Optional[Callable[[str], int]] = None,
        min_header_field_count: int = MIN_HEADER_FIELD_COUNT,
        scan_text_layer_probe: Optional[Callable[[bytes], bool]] = None,
        signature_probe: Optional[Callable[[str], bool]] = None,
    ) -> None:
        """Zinciri başlat.

        Args:
            extractors: Sırayla denenecek aday çıkarıcılar.
            min_char_count: Kalan çıkarıcılar denenmeden bir sonucun kabul
                edilebileceği karakter sayısı eşiği.
            min_quality_ratio: Bir sonucun okunabilir sayılması için ulaşması
                gereken kelime uzunluğundaki jeton payı.
            header_repair: Her OCR sonucunun ilk sayfasının başlık bandını
                onarmak için kullanılan isteğe bağlı vision çıkarıcı (bkz.
                `_maybe_repair_header`) -- genellikle `extractors` içinde
                zaten bulunan aynı örnek, aranmak yerine burada açıkça
                tekrar geçirilir, böylece bunu atlayan bir çağıran, sessiz
                isinstance eşleştirmesi yerine başlık onarımı hiç olmayan
                bir zincir alır. None adımı tamamen devre dışı bırakır.
                Ayrıca `MAX_OCR_PAGES` için *tam sayfa* vision yükselmesi
                olarak ele alınan çıkarıcıdır (bkz. `extract`).
            header_field_probe: Bir belgenin öngörülen başlık alanlarından
                (sayi/tarih/konu/muhatap/gonderen_kurum) kaçının bir metin
                sayfasından ayrıştığını sayan isteğe bağlı çağrılabilir --
                genellikle `app.ai.compliance.count_header_fields`. Bu
                infrastructure katmanı modülünün `app.ai` katmanına asla
                bağımlı olmaması için doğrudan import edilmek yerine açıkça
                geçirilir (`header_repair`'in enjekte edilmesinin aynı
                nedeni). None, alan-farkında kabul kriterini tamamen devre
                dışı bırakır, tam olarak bugünkü yalnızca karakter/kalite
                kabulünü geri getirir -- bkz. `_has_enough_header_fields`.
            min_header_field_count: Karakter/kalite zaten geçtikten sonra,
                bir sonucun doğrudan kabul edilebilmesi için 1. sayfanın
                `header_field_probe` sonucunun ulaşması gereken minimum
                değer. `MIN_HEADER_FIELD_COUNT`'in kendi yorumunda
                kalibre edilmiştir; yalnızca `header_field_probe`
                ayarlandığında dikkate alınır.
            scan_text_layer_probe: Bir belgenin gömülü metin katmanının,
                gerçekten dijital doğan bir metin katmanı yerine tam sayfa
                bir tarama görüntüsünün üzerinde oturan tarayıcı kaynaklı
                çöp olup olmadığını bildiren isteğe bağlı çağrılabilir
                (Class A -- bkz.
                `app.infrastructure.extractors.base.is_scanned_text_layer`).
                `_maybe_repair_header`'ın kapısını, o sonuç için
                `used_ocr` False olsa bile bu sınıfı da onaracak şekilde
                genişletir. None bu genişletmeyi devre dışı bırakır, bu
                yüzden bunu atlayan bir çağıran, başlık onarımını bu
                parametre var olmadan önce olduğu gibi yalnızca `used_ocr`'a
                kilitlenmiş tutar.
            signature_probe: Bir belgenin imza sahibi adının
                (`imza_sahibi`) bir metin sayfasından ayrışıp ayrışmadığını
                bildiren isteğe bağlı çağrılabilir -- genellikle
                `app.ai.compliance.has_signature`. `header_field_probe` ile
                aynı şekilde ve aynı nedenle enjekte edilir. İmzanın
                ayrışamaz olduğunu bildirdiğinde, `_maybe_repair_page_one`
                1. sayfayı yalnızca başlık bandı kırpımı yerine tamamen bir
                tam sayfa vision transkripsiyonuyla değiştirir (bkz.
                `_repair_full_page`) -- başlık bandı onarımı tek başına bir
                imza bloğuna ulaşamaz, o başlığın çok altında yer alır.
                None imza kurtarma yükselmesini tamamen devre dışı bırakır,
                tam olarak bugünkü yalnızca başlık bandı onarımını geri
                getirir.
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
        """Bir sonucun zinciri durduracak kadar iyi olup olmadığını bildirir.

        Her iki kontrol de gereklidir. Yalnızca uzunluk OCR çöpünü kabul
        eder: bozuk bir taramada Tesseract 758 karakterlik anlamsız metin
        döndürdü, uzunluk eşiğini rahatça geçti, ve zincir orada durup hiç
        başlık alanı bildirmezdi.

        Args:
            result: Bir aday çıkarım.

        Returns:
            Sonuç yeterince uzun ve yeterince okunabilirse True. Bu,
            başlık alanı kurtarma konusunda bilinçli olarak sessizdir --
            bkz. `_has_enough_header_fields`, ayrı, daha sonra uygulanan
            bir kriter.
        """
        return (
            result.char_count >= self.min_char_count
            and result.quality_ratio >= self.min_quality_ratio
        )

    def _page_one(self, result: ExtractedDocument) -> str:
        """`header_field_probe`/onarımın hakkında akıl yürüttüğü metin: yalnızca 1. sayfa.

        Belge geneli skorlama, bir 1. sayfa başlık başarısızlığını daha
        sonraki bir sayfanın kendi başlığının arkasına gizler (kendi
        `Konu:`'suna sahip ekli bir mektup taşıyan çok sayfalı bir yanıt,
        bunun karşı korunduğu gerçek durumdur -- bkz. `count_header_fields`'ın
        kendi docstring'i), bu yüzden bu sınıftaki her alan-farkında karar
        her zaman özellikle 1. sayfa hakkında akıl yürütür, asla birleşim
        hakkında değil.
        """
        return result.pages[0] if result.pages else result.text

    def _header_field_count(self, result: ExtractedDocument) -> int:
        """`header_field_probe`'un 1. sayfadan kaç başlık alanı kurtardığı.

        Hiç sonda yapılandırılmamışsa 0 döner, bu da `_rank_key`'in bu
        bileşenini bir tane enjekte etmeyen çağıranlar için etkisiz tutar --
        sıralama o zaman tam olarak önceden var olan yalnızca kalite
        karşılaştırmasına indirgenir.
        """
        if self.header_field_probe is None:
            return 0
        return self.header_field_probe(self._page_one(result))

    def _has_enough_header_fields(self, result: ExtractedDocument) -> bool:
        """1. sayfanın başlık bloğunun gerçekten ayrışıp ayrışmadığını bildirir.

        Belge geneli bir düzyazı okunabilirlik ortalaması (`quality_ratio`)
        bunu göremez: bozuk bir `sayi` veya ayrışamayan bir `konu` satırı,
        aksi halde mükemmel okunabilir Türkçe düzyazının içinde
        oturabilir (gerçek bir belgede ölçüldü: 0.85 quality_ratio, beş
        başlık alanından sıfırı kurtarıldı). Bu, bunu yakalayan ikinci,
        daha sonra uygulanan kabul kapısıdır.

        Returns:
            Hiç `header_field_probe` yapılandırılmamışsa koşulsuz True --
            bu kriter buna katılmayan bir çağıran için kendi başına
            hiçbir şeyi asla reddetmemelidir.
        """
        if self.header_field_probe is None:
            return True
        return self._header_field_count(result) >= self.min_header_field_count

    def _is_scan_text_layer(self, content: bytes) -> bool:
        """`scan_text_layer_probe` yapılandırılmamışsa False.

        `_maybe_repair_header`'ın genişletilmiş kapısını varsayılan olarak
        etkisiz tutar, `_has_enough_header_fields`'in sonda-yok
        varsayılanıyla aynı şekil.
        """
        if self.scan_text_layer_probe is None:
            return False
        return self.scan_text_layer_probe(content)

    def _header_repair_would_regress(
        self, original: ExtractedDocument, candidate: ExtractedDocument
    ) -> bool:
        """Whether `candidate`'s page 1 recovers fewer header fields than
        `original`'s did, via `header_field_probe`.

        Deliberately header-only, not signature-aware -- unlike
        `_repair_would_regress`. `_maybe_repair_header` is never the last
        word on a document: `_maybe_repair_page_one` inspects *its* return
        value afterward to decide whether the signature survived the crop
        and, if not, escalates to `_repair_full_page`. If this check also
        reverted on signature loss, it would silently swallow that signal
        before `_maybe_repair_page_one` ever saw it -- the document would
        keep its unrepaired header (no worse, but no better either) instead
        of reaching the full-page transcription that could fix both.

        Measured on the real corpus: header-band repair dropped CY-050 from
        3/3 header fields to 2/3, which still cleared
        `_has_enough_header_fields`'s floor (`MIN_HEADER_FIELD_COUNT`), so
        it would not have been caught by the acceptance gate downstream.

        Returns:
            False when no `header_field_probe` is configured, keeping this
            check inert for callers that didn't opt in -- same default
            shape as `_has_enough_header_fields`.
        """
        return self._header_field_count(candidate) < self._header_field_count(original)

    def _repair_would_regress(
        self, original: ExtractedDocument, candidate: ExtractedDocument
    ) -> bool:
        """Whether `candidate`'s page 1 recovers fewer prescribed fields
        than `original`'s did -- header fields (see
        `_header_repair_would_regress`), or a signature that was parseable
        in `original` and isn't in `candidate`. Either counts as a
        regression.

        Used only by `_repair_full_page`, the strongest repair available
        and the last one `_maybe_repair_page_one` will try -- there is no
        further escalation to fall through to, so this is the one place
        that must catch a regression on *either* axis before committing to
        it. Measured on the real corpus: full-page repair dropped three
        documents from 4/4 header fields to 3/4. A vision transcription
        that reads a genuine document worse than the text it was meant to
        repair must never be trusted just because it came from a "smarter"
        model -- this makes every repair step in this class monotonic: it
        may only add fields back, never take them away.

        Returns:
            False when neither probe is configured, keeping this check
            inert for callers that opted into neither -- same default
            shape as `_has_enough_header_fields`.
        """
        if self._header_repair_would_regress(original, candidate):
            return True
        if (
            self.signature_probe is not None
            and self.signature_probe(self._page_one(original))
            and not self.signature_probe(self._page_one(candidate))
        ):
            return True
        return False

    def _rank_key(self, result: ExtractedDocument) -> tuple[int, float]:
        """En iyi çaba aday seçimi için sıralama anahtarı.

        Önce başlık alan sayısı, berabere bozma olarak `quality_ratio` --
        böylece hiçbir şey her iki kabul kapısını geçemediğinde, en fazla
        öngörülen başlık alanı kurtaran aday, genel olarak daha "okunabilir"
        birine karşı bile kazanır, ve eşit alan sayıları (hiç
        `header_field_probe` yapılandırılmadığında evrensel 0 dahil) tam
        olarak bugünkü yalnızca okunabilirlik karşılaştırmasına geri döner.
        """
        return (self._header_field_count(result), result.quality_ratio)

    async def _rasterise_page_one(self, content: bytes, raster_cache: dict):
        """Vision onarımı için rasterize edilmiş bir 1. sayfa görüntüsü döndür.

        `_maybe_repair_header` ve `_repair_full_page` tarafından paylaşılır
        -- ikisi de tam olarak bu görüntüye, tam olarak aynı kaynaktan, tam
        olarak `self.header_repair.dpi`'de ihtiyaç duyar, bu yüzden
        `raster_cache`'i yeniden kullanan ya da yeniden render etmeye
        düşen tam olarak tek bir yer vardır.

        Args:
            content: `raster_cache`'in `header_repair.dpi`'de hiçbir şeyi
                olmadığında (Class-A durumu: çıkarıcısı hiçbir şeyi
                rasterize etmez) 1. sayfayı kendi kendine rasterize etmek
                için gereken ham belge byte'ları.
            raster_cache: Zincirin çıkarıcılarının rasterize ettiği aynı
                önbellek -- hiçbir sayfanın ikinci kez render edilmemesi
                için burada yeniden kullanılır.

        Returns:
            Görüntü, ya da rasterizasyon mümkün değilse veya başarısız
            olursa None -- çağıranlar bunu "onarım kullanılamıyor" olarak
            ele almalı, asla yeniden denememeli.
        """
        images = raster_cache.get(self.header_repair.dpi)
        if images:
            return images[0]
        # Bu zincir tarafından hiç rasterize edilmemiş (Class A: çıkarıcısı
        # metin katmanını doğrudan okudu ve hiçbir şey render etmedi) --
        # 1. sayfayı kendimiz render edelim. Bilinçli olarak raster_cache'e
        # YAZILMIYOR: buradaki kısmi, yalnızca-1.-sayfa bir girdi, daha
        # sonraki tam belge OCR geçişinin sessizce yalnızca 1. sayfayı
        # transkribe edip belgenin geri kalanını düşürmesine neden olurdu.
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
        """1. sayfayı vision ile onar -- başlık bandı, ya da başlık bandı
        kırpımı eksik olanı yakalayamadığında (ayrışamayan bir imza, ya da
        kırpımdan sonra hâlâ ayrışmayan bir başlık alanı), bunun yerine tüm
        sayfa.

        Yaygın durumda tam olarak `_maybe_repair_header` (yalnızca kırpım,
        bugünkü davranış) veya `_repair_full_page` (tam sayfa değişimi)
        ikisinden birine dallanır -- bir belge o zaman iki vision
        maliyetinden yalnızca birini öder. `signature_probe` hangisine
        önceden karar verir: başlık bandı onarımı tek başına bir imza
        bloğuna ulaşamaz, başlık bandının (`HEADER_BAND_FRACTION`) çok
        altında yer alır, bu yüzden imza sahibinin adı hiç ayrışamadığında,
        gerçekten ona ulaşma şansı olan şey tam sayfa transkripsiyonudur --
        ve o transkripsiyon zaten başlığı da kapsar, bu yüzden sonradan
        ayrıca kırpmak aynı sayfa için iki kez ödemek olurdu. Bunun
        arkasındaki ölçüm için `_repair_full_page`'in kendi docstring'ine
        bakın.

        İki durum, aynı yükselme ihtiyacını yalnızca kırpım *zaten
        çalıştıktan sonra* tespit eder:

        - Başlık bandı onarımının kendi birleştirmesi yalnızca sayfanın
          önde gelen `HEADER_REPAIR_LINE_COUNT` satırlarını değiştirir,
          tipik çok paragraflı bir mektup için kalibre edilmiş bir
          yaklaşım -- kısa bir belgede (gerçek korpus üzerinde ölçüldü:
          CY-003/023/028, her biri kısa tek paragraflık bir yanıt) imza
          bloğunun kendisi o aralığın içine düşebilir, ve birleştirme onu,
          onarım öncesi metinden gayet iyi ayrışmış olsa bile sessizce
          atar. Nadir (ölçülen korpusta 23'te 3) ve gerçekleştiğinde çift
          vision maliyetine değer: gerçek bir imza sahibini eksik zorunlu
          alan olarak raporlamak, bir yavaş yüklemeden daha kötüdür.
        - Kırpım yalnızca sayfanın üst `HEADER_BAND_FRACTION`'ını kapsar --
          o satırın altındaki öngörülen bir başlık alanı, kırpım için tam
          olarak bir imza kadar ulaşılamazdır (gerçek korpus üzerinde
          ölçüldü: başlık bandı onarımı zaten çalıştıktan sonra başlık
          alanlarında eksik kalan 9 belgeden 6'sı yalnızca kırpım yolunu
          izledi, hiç yükselmedi, çünkü imzaları baştan sona gayet iyi
          ayrıştı).

        Her iki yükselme de 1. sayfayı *orijinal*, onarım öncesi
        `result`'tan değiştirir, asla kırpımın kendi çıktısından değil --
        `_repair_full_page` içeride `result`'tan daha az alan kurtaran
        hiçbir şeyi tutmayı reddeder (bkz. `_repair_would_regress`), bu
        yüzden bu metodun iki adayı kendisinin karşılaştırmasına hiç
        gerek yoktur.

        Args:
            result: Zincirin seçtiği sonuç.
            raster_cache: Zincirin çıkarıcılarının rasterize ettiği aynı önbellek.
            content: Ham belge byte'ları.
            repair_cache: Bu tek `extract()` çağrısı için, her iki onarım
                yolu arasında paylaşılan bellekleme (her biri ayrı anahtarlı).

        Returns:
            `result`, hangi yol uygulandıysa onunla onarılmış, ya da hiçbiri
            uygulanmadıysa (veya denenen her onarım geriletme olacaksa)
            değişmemiş.
        """
        if self.header_repair is None or not result.pages:
            return result
        if not result.used_ocr and not self._is_scan_text_layer(content):
            return result
        if self.signature_probe is not None and not self.signature_probe(
            self._page_one(result)
        ):
            return await self._repair_full_page(
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
            return await self._repair_full_page(
                result, raster_cache, content, repair_cache
            )
        if not self._has_enough_header_fields(repaired):
            logger.info(
                "Header-band repair on [%s] still left page 1 with only %d "
                "of the prescribed header fields (floor %d) -- the missing "
                "field(s) may sit below the repaired band; escalating to a "
                "full-page transcription instead.",
                result.extractor,
                self._header_field_count(repaired),
                self.min_header_field_count,
            )
            return await self._repair_full_page(
                result, raster_cache, content, repair_cache
            )
        return repaired

    async def _repair_full_page(
        self,
        result: ExtractedDocument,
        raster_cache: dict,
        content: bytes,
        repair_cache: dict,
    ) -> ExtractedDocument:
        """En iyi çaba: 1. sayfayı tamamen tam sayfa bir vision
        transkripsiyonuyla değiştir, başlık bandı onarımının ulaşamadığı
        iki başarısızlık modu için: ayrışamayan bir imza, ya da onarılmış
        bandın altında oturan bir başlık alanı.

        Başlık bandı onarımı yalnızca sayfanın üst `HEADER_BAND_FRACTION`'ına
        dokunur, ama bir imza bloğu onun çok altında yer alır -- bu yüzden
        hiçbir miktarda başlık bandı onarımı, basılı metnin üzerindeki ıslak
        imza mürekkebi tarafından bozulan veya tanınmaz hale getirilen bir
        imza sahibinin adını kurtaramaz. OpenDataLoader/Tesseract'ın imza
        satırını tamamen kaybettiği veya tanınmaz biçimde bozduğu dört gerçek
        belge üzerinde doğrudan ölçüldü (`"Bekir BOZDAĞ"` için
        `"İF; BOZDAG ;"`): tam sayfa vision transkripsiyonu dördünde de
        doğru ismi kurtardı (bkz. `OllamaVisionExtractor.transcribe_page`'in
        kendi docstring'i). Aynı kör nokta, kırpımın altında oturan başka
        herhangi bir öngörülen başlık alanı için de geçerlidir --
        `_maybe_repair_page_one`, yalnızca başlık bandı onarımı tek başına
        yetersiz kaldığında da bu yüzden bu metoda ulaşır.

        `_maybe_repair_page_one` tarafından her iki nedenle de çağrılır --
        bu metodun kendisi hangisinin geçerli olduğunu yeniden kontrol
        etmez, bu yüzden başarıyla bir şey transkribe ettiğinde her zaman
        1. sayfayı değiştirmeye çalışır. *Gerçekten* kontrol ettiği şey, bu
        değişimin değiştirdiği şeyden gerçekten daha iyi olup olmadığıdır
        (bkz. `_repair_would_regress`): tam sayfa transkripsiyonu mevcut en
        güçlü onarımdır, ama "en güçlü" "kesinlikle doğru" anlamına gelmez
        -- gerçek korpus üzerinde ölçüldü, üç belgeyi 4/4 başlık alanından
        3/4'e düşürdü.

        Args:
            result: Zincirin seçtiği sonuç, ve `_repair_would_regress`'in
                transkripsiyonu karşılaştırdığı referans.
            raster_cache: Zincirin çıkarıcılarının rasterize ettiği aynı
                önbellek -- hiçbir sayfanın ikinci kez render edilmemesi
                için burada yeniden kullanılır.
            content: `_rasterise_page_one` için ham belge byte'ları.
            repair_cache: Bu tek `extract()` çağrısının onardığı her aday
                arasında tam sayfa transkripsiyonu belleklemesi, başlık
                bandı onarımının anahtarından ayrı kendi anahtarı altında
                (`_REPAIR_PAGE_CACHE_KEY`) -- başlık bandı onarımı bu
                tetiklendiğinde zaten çalışmış ve atılmış olabilir (bkz.
                `_maybe_repair_page_one`), bu yüzden iki anahtar, sözlüğün
                ömrünü paylaşsalar bile bağımsız olarak doldurulur.

        Returns:
            İlk sayfası vision modelinin tam transkripsiyonuyla değiştirilmiş
            `result`, ya da herhangi bir başarısızlıkta, boş çıktıda veya
            `result`'ın zaten sahip olduğundan daha az alan kurtaran bir
            transkripsiyonda tamamen değişmemiş `result` -- bu adım çalışan
            bir çıkarımı asla başarısız birine dönüştürmemelidir.
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
                    "Full-page repair failed for [%s]; keeping its "
                    "original text.",
                    result.extractor,
                    exc_info=True,
                )
                return result
            page_text = page_text.strip()
            repair_cache[_REPAIR_PAGE_CACHE_KEY] = page_text

        if not page_text:
            return result

        pages = [page_text, *result.pages[1:]]
        candidate = result.model_copy(
            update={"pages": pages, "text": "\n\n".join(pages).strip()}
        )
        if self._repair_would_regress(result, candidate):
            logger.info(
                "Full-page transcription of [%s] recovered fewer fields "
                "than the original (%d header field(s) vs %d); keeping "
                "the original text.",
                result.extractor,
                self._header_field_count(candidate),
                self._header_field_count(result),
            )
            return result

        logger.info(
            "Replaced [%s]'s first page with a full-page vision "
            "transcription (%d characters).",
            result.extractor,
            len(page_text),
        )
        return candidate

    async def _maybe_repair_header(
        self,
        result: ExtractedDocument,
        raster_cache: dict,
        content: bytes,
        repair_cache: dict,
    ) -> ExtractedDocument:
        """En iyi çaba: bir OCR sonucunun ilk sayfasının başlık bandını değiştir.

        Herhangi bir kalite skoruna bağlı olmadan her OCR sonucuna
        koşulsuz uygulanır: bunun için inşa edilen gerçek taranmış korpusa
        (datasets/resmi_yazisma/00_gelen_kaynaklar/cevap_yazisi/ altında
        45 belge) karşı bir tetikleyiciyi (başlık sembol-gürültü
        yoğunluğu) kalibre etmek, bilinen ayrıştırıcı boşlukları kontrol
        edildiğinde bile bunu buna ihtiyacı olandan güvenilir biçimde
        ayıran hiçbir sinyal bulamadı -- Pearson r'si 0.036 kadar düşük.
        Her zaman yalnızca kırpım vision maliyetini ödemek (~12.6s ölçüldü,
        tam sayfa için ~26s değil), çalışan bir tetikleyici yerine kabul
        edilen bilinçli takastı. HEADER_BAND_FRACTION'ın kendi yorumuna
        bakın.

        Ayrıca, `scan_text_layer_probe` aracılığıyla, ikinci bir sonuç
        sınıfına da genişletildi: bir "Class A" tarayıcı metin katmanının
        (bkz. `app.infrastructure.extractors.base.is_scanned_text_layer`)
        `used_ocr=False`'u vardır -- OpenDataLoader/Pdfium onu gerçek bir
        metin katmanıymış gibi okur -- ama gerçek OCR çıktısı kadar
        bozuktur, bu yüzden bayrağa rağmen aynı onarıma ihtiyaç duyar.

        Args:
            result: Zincirin seçtiği sonuç. En az bir sayfası olan OCR
                çıktısı (veya bir Class-A tarama metin katmanı) değilse ve
                bir `header_repair` çıkarıcısı yapılandırılmadıysa
                değişmeden döndürülür.
            raster_cache: Zincirin çıkarıcılarının rasterize ettiği aynı
                önbellek -- hiçbir sayfanın ikinci kez render edilmemesi
                için burada yeniden kullanılır.
            content: `raster_cache`'in `header_repair.dpi`'de hiçbir şeyi
                olmadığında (Class-A durumu: çıkarıcısı hiçbir şeyi
                rasterize etmez) 1. sayfayı kendi kendine rasterize etmek
                için gereken ham belge byte'ları.
            repair_cache: Bu tek `extract()` çağrısının onardığı her aday
                arasında kırpım transkripsiyonunu bellekler -- kırpım
                hepsi için aynıdır (aynı görüntü, aynı model, sıcaklık 0),
                bu yüzden bu olmadan birkaç adayın ötesine yükselen bir
                belge, belge başına bir kez yerine aday başına bir kez
                vision modeli maliyeti öderdi.

        Returns:
            İlk sayfasının önde gelen `HEADER_REPAIR_LINE_COUNT` satırları
            vision modelinin o bandın transkripsiyonuyla değiştirilmiş
            `result`, ya da herhangi bir başarısızlıkta, boş çıktıda veya
            `result`'ın zaten sahip olduğundan daha az başlık alanı
            kurtaran bir kırpımda (bkz. `_header_repair_would_regress`)
            tamamen değişmemiş `result` -- bu adım çalışan bir çıkarımı
            asla başarısız birine dönüştürmemelidir.
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
        candidate = result.model_copy(
            update={"pages": pages, "text": "\n\n".join(pages).strip()}
        )
        if self._header_repair_would_regress(result, candidate):
            logger.info(
                "Header-band repair on [%s] recovered fewer fields than "
                "the original (%d header field(s) vs %d); keeping the "
                "original text.",
                result.extractor,
                self._header_field_count(candidate),
                self._header_field_count(result),
            )
            return result

        logger.info(
            "Repaired the header band of [%s]'s first page (%d characters).",
            result.extractor,
            len(header_text),
        )
        return candidate

    async def extract(
        self,
        content: bytes,
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        raster_cache: Optional[dict] = None,
    ) -> ExtractedDocument:
        """Kullanılabilir bir sonuç üreten ilk çıkarıcıyı kullanarak metin çıkar.

        Doğrudan döndürülebilmesi için bir adayın iki bağımsız kapıyı
        geçmesi gerekir: `_is_acceptable` (yeterince uzun, yeterince
        okunabilir) ve bu geçtikten ve başlık onarımı şansını
        kullandıktan sonra, `_has_enough_header_fields` (1. sayfanın
        öngörülen alanları gerçekten ayrıştı). Birinciyi geçip ikinciyi
        geçemeyen bir aday döndürülmez -- diğer herhangi bir
        karakter/kalite reddi gibi bir en iyi çaba adayı olur, ve zincir
        bir sonraki çıkarıcıyı dener. Bu, zincirin, metni genel olarak iyi
        Türkçe düzyazı okusa da başlık bloğu bozuk olan bir Class-A tarama
        gibi bir belge için son çare vision çıkarıcısına ulaşmasını sağlar.

        Args:
            content: Ham belge byte'ları.
            file_name: Yönlendirme için kullanılan orijinal dosya adı.
            mime_type: Yönlendirme için kullanılan bildirilen içerik türü.
            raster_cache: Bu zincir başka bir çağıran altında iç içeyse,
                onurlandırılan önceden var olan bir raster önbelleği.
                Aksi halde çağrı başına yeni oluşturulur, böylece bu
                *zincirde* bir OCR çıkarıcısından diğerine yükselen taranmış
                bir PDF, iki ilgisiz belge arasında hiçbir şey sızdırmadan
                zaten render edilmiş sayfaları yeniden kullanır.

        Returns:
            Her iki kapıyı da karşılayan ilk sonuç, ya da görülen en zengin sonuç.

        Raises:
            DocumentExtractionError: Hiçbir çıkarıcı uygulanmazsa veya hepsi başarısız olursa.
        """
        if raster_cache is None:
            raster_cache = {}
        # Bu çağrının onardığı her aday arasında başlık bandı kırpımı
        # transkripsiyonunu bellekler -- bkz. `_maybe_repair_header`'ın
        # kendi docstring'i. Her `extract()` çağrısında yeni, `raster_cache`
        # ile aynı ömür, böylece iki ilgisiz belge arasında hiçbir şey sızmaz.
        repair_cache: dict = {}
        best: Optional[ExtractedDocument] = None
        # `best`'in aşağıdaki döngü içinde `_maybe_repair_header`'dan zaten
        # geçip geçmediği. Döngü çıkışındaki dönüşte onu ikinci kez onarmak,
        # ilk HEADER_REPAIR_LINE_COUNT satırını -- o zamana kadar onarılmış
        # başlık artı gerçek gövde satırları olan -- yeniden değiştirir --
        # sessizce gövde metnini siler (çift birleştirme).
        best_repaired = False
        last_error: Optional[Exception] = None
        attempted = 0
        # En son çalışan çıkarıcıdan görülen en son sayfa sayısı -- yalnızca
        # *tam sayfa* vision yükselmesinin (belge uzunluğundan bağımsız
        # olarak her zaman yalnızca 1. sayfa olan başlık bandı onarımının
        # aksine) kendi maliyetine değip değmediğine karar vermek için
        # kullanılır. MAX_OCR_PAGES'in kendi yorumuna bakın.
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
