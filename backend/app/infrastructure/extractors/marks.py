"""İmzaların, mühürlerin ve el yazısı notların en iyi çaba tespiti.

Saf `numpy` + `Pillow` -- her ikisi de zaten çalışan imajda mevcut (`scipy`,
`cv2`, `onnxruntime`, veya `torch` yok; bu modülün üzerine inşa edildiği
tasarım notlarına bakın). Doğrudan zaten rasterize edilmiş bir sayfanın
ikili-benzeri mürekkep maskesi üzerinde çalışır: kaba bir yoğunluk ızgarası
üzerinde bağlı bileşen analizi, ardından küçük bir şekil sezgisi seti
(vuruş genişliği varyansı, taban çizgisi düzensizliği, en-boy oranı, mürekkep
yoğunluğu) imza/mühür/el yazısı şeklindeki mürekkebi basılı metinden ayırır.

Bu bir inceleme ipucudur, adli bir belirleme değildir, ve modül boyunca bu
sınırlama konusunda açıktır: bu proje belge korpusu için elle etiketlenmiş
bir imza veya mühür veri kümesi yoktur, bu yüzden burada hiçbir şeyin
ölçülmüş bir kesinlik ya da geri çağırma değeri yoktur -- yalnızca gerçek
taramalara karşı tespit *sayıları* vardır (bkz. `scripts/evaluate_marks.py`).
`check_required_fields`, tespit edilen bir imzayı bir belgenin imzalı
olduğuna dair kanıt olarak ele alır; kaçırılan bir tanesi yasal bir
belirleme değil, yanlış bir "eksik bilgi"dir, bu yüzden çağıranlar bunu bir
kişinin doğrulaması gereken bir şey olarak sunmaya devam etmelidir.

Bilinçli olarak piksel başına bağlı bileşen etiketleyicisi değildir
(`scipy.ndimage.label` yok): sayfa önce `_GRID_CELL_PX` boyutlu hücrelere
bölünür, mürekkep yoğunluğu hücre başına hesaplanır (tamamen vektörize),
ve yalnızca ortaya çıkan birkaç bin hücrelik ızgara düz Python'da flood-fill
yapılır -- bağımlılık olmadan yeterince hızlı, alt-hücre kesinliğini
kaybetme pahasına, ki bu sezgi buna ihtiyaç duymaz.
"""

import logging
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

try:  # pragma: no cover - testlerde patch ile çalıştırılır
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:  # pragma: no cover
    from PIL import Image as _PILImage
except ImportError:  # pragma: no cover
    _PILImage = None


class DetectedMark(BaseModel):
    """Muhtemelen bir imza, mühür veya el yazısı not olarak işaretlenen bir
    mürekkep bölgesi. Bir sezgisel inceleme ipucu -- bkz. modül docstring'i."""

    kind: str = Field(description="'signature', 'stamp' veya 'handwriting'.")
    page: int = Field(description="1 tabanlı sayfa numarası.")
    bbox: tuple[int, int, int, int] = Field(
        description=(
            "(x0, y0, x1, y1) -- sayfa genişliği/yüksekliğinden bağımsız "
            "olması için 0-1000 ölçeğine normalize edilmiştir."
        )
    )
    confidence: float = Field(
        description="0.0-1.0 arası kaba güven skoru; adli değil, gözden geçirme amaçlıdır."
    )


#: Kaba yoğunluk taraması için ızgara hücresi kenar uzunluğu, piksel
#: cinsinden. OCR_RENDER_DPI'de (300) vuruş ölçeğinde mürekkebi çözebilecek
#: kadar küçük, ızgarayı flood-fill yapmayı (vektörize değil, düz Python)
#: hızlı tutacak kadar büyük -- tam bir 2496x3508 sayfa (bu projenin tipik
#: taranmış sayfa çözünürlüğü), 8.7 milyon piksel değil, kabaca 125x175
#: hücreye ızgaralanır.
_GRID_CELL_PX = 20
#: Bir hücre bu siyah piksel oranının üzerinde "mürekkepli" sayılır.
_CELL_INK_THRESHOLD = 0.08
#: Mürekkebi kağıttan ayıran sabit gri tonlama eşiği. Otsu ya da başka bir
#: adaptif yöntem değil -- bunun için inşa edildiği korpus
#: (datasets/resmi_yazisma/00_gelen_kaynaklar/cevap_yazisi/) zaten neredeyse
#: ikili CCITT-G4 taramalarıdır, bu yüzden sabit bir eşik yeterlidir ve
#: yanlış yapılacak bir şey daha azdır.
_INK_GRAY_THRESHOLD = 128
#: Sayfa genişliğinin bu oranından daha fazla yayılan bir bileşen bir işaret
#: değil, bir metin satırı veya antettir -- bu filtre olmadan her gövde
#: metni paragrafı işaretlenirdi.
_MAX_MARK_WIDTH_FRACTION = 0.5
#: Hiç dikkate alınması için ızgara hücresi cinsinden minimum bileşen
#: boyutu. Yalıtılmış basılı karakterleri, noktalama işaretlerini ve
#: tarama gürültüsünü filtreler.
_MIN_COMPONENT_CELLS = 6
#: Bu kadar kompakt (kareye yakın), bu kadar yoğun, ve birçok kısa mürekkep
#: koşusundan oluşan (hemen aşağıdaki `_STAMP_MIN_RUN_DENSITY`'ye bakın) bir
#: bileşen, aşağıdaki vuruş/taban çizgisi kontrollerinden geçirilmek yerine
#: bir mühür adayı olarak ele alınır -- resmi bir mühür veya antetli kaşe
#: incelikli bir sanat eseridir (metin halkası, arma), bir kalem vuruşu
#: satırı değil. Bu modülün hedeflediği gerçek taranmış korpusa karşı
#: ölçüldüğünde (bkz. `scripts/evaluate_marks.py`): gerçek bir Türkçe resmi
#: mühür yaklaşık 3.5-4cm (yaklaşık 1.4-1.6in) çapındadır, bu yüzden
#: `_STAMP_MIN_DIMENSION_PX` bunun oldukça altında ayarlanmıştır (yine de
#: daha küçük veya kısmen taranmış bir mührü kaçırmaktansa aşırı tespit
#: yönünde hata yapar), tam onda değil.
_STAMP_ASPECT_RATIO_RANGE = (0.55, 1.8)
_STAMP_MIN_INK_DENSITY = 0.12
#: OCR_RENDER_DPI (300) varsayılarak piksel cinsinden -- bu modülün aldığı
#: her sayfa tam olarak o yoğunlukta render edilir (bkz.
#: BaseDocumentExtractor.extract'ın DPI'ya göre anahtarlanan raster_cache'i,
#: TesseractExtractor/OllamaVisionExtractor'ın ikisinin de tam olarak o
#: değerde doldurduğu).
_STAMP_MIN_DIMENSION_PX = 150
#: Bir mühür şeklindeki adayın gerçekten öyle sınıflandırılması için
#: bölgenin 100px genişliği başına ortalama ayrı yatay mürekkep koşusu
#: sayısı (bkz. `_stroke_run_density`). Ground-truth etiketlemesinden sonra
#: eklendi (15 gerçek belge, bkz.
#: datasets/resmi_yazisma/ocr_ground_truth.json), bu modülün %0 imza geri
#: çağırma bildirmesini buldu: gerçek bir el yazısı imza, kabaca kare ve
#: yukarıdaki şekil/boyut kontrollerini tek başına karşılayacak kadar yoğun
#: olabilir (CY-012'nin gerçek ıslak imzası "Yaşar GÜLER" üzerinde en-boy
#: oranı 1.69, yoğunluk 0.121, boyut 320x540px ölçtü -- yukarıdaki her
#: eşiğin rahatça içinde), bu yüzden bu kapı olmadan mühür dalı, aşağıdaki
#: vuruş/taban çizgisi kontrolleri hiç çalışmadan gerçek imzaları
#: yakalıyordu. Gerçek korpus üzerinde ölçüldüğünde, koşu yoğunluğu iki
#: popülasyonu net biçimde ayırır: bir antetli kaşenin incelikli sanat
#: eseri 2.18-9.28 arasında koşar (bu korpusun kendi antetindeki
#: T.C./bakanlık amblemi için ortalama ~2.2), mühür şekil kontrolünü de
#: geçen her onaylanmış gerçek imza ise 1.26-1.30 ölçtü -- dar değil geniş
#: bir boşluk, bu yüzden bu kırılgan bir eşik değildir.
_STAMP_MIN_RUN_DENSITY = 2.0
#: Bunun üzerinde mürekkebin basılıdan (tek biçim glif vuruş genişliği)
#: ziyade el yazısı (düzensiz kalem basıncı/açısı) olarak okunduğu vuruş
#: genişliği varyasyon katsayısı. Tek başına bu, kısa basılı bir ifadeyi
#: el yazısı bir işaretten ayırmaz -- bunu yapan _MAX_STROKE_RUN_DENSITY'ye
#: bakın.
_HANDWRITING_MIN_STROKE_CV = 0.5
#: Üzerinde bir bölgenin paylaşılan bir taban çizgisi dışında oturduğu
#: okunduğu -- basılı metnin hizalı taban çizgisinin aksine el yazısı veya
#: başka türlü düzensiz -- sütun başına mürekkep-üstü konumunun normalize
#: edilmiş standart sapması. Yukarıdaki _HANDWRITING_MIN_STROKE_CV ile aynı
#: uyarı.
#:
#: Mühür-müdahale hatası yukarıda düzeltildikten sonra bile bu eşiğin
#: gerçek imzaları engellediğini bulan aynı ground-truth etiketlemesinden
#: sonra 0.15'ten düşürüldü: CY-012/CY-009/CY-006'nın onaylanmış veya
#: yüksek olasılıklı imzaları, orijinal 0.15 tabanının altında,
#: baseline_std 0.119-0.139 ölçtü -- bir imzanın kalem vuruşları hâlâ
#: nispeten tutarlı bir yükseklikten başlar (kabaca bir çizgi boyunca
#: yazılmış bir isimdir, dağınık bir kenar notu gibi değil), bu yüzden
#: notlar için kalibre edilen genel "el yazısı" eşiği özellikle imzalar
#: için çok katıydı. Düşürüldükten sonra tam 45 belgelik korpusa karşı
#: yeniden doğrulandı (bkz. scripts/evaluate_marks.py) ki bu,
#: _MAX_STROKE_RUN_DENSITY'nin düzeltmek için eklendiği orijinal
#: bir-sayfada-24 aşırı tetikleme sorununu yeniden açmıyor.
_HANDWRITING_MIN_BASELINE_STD = 0.10
#: Bölgenin 100px genişliği başına maksimum ortalama ayrı yatay mürekkep
#: koşusu sayısı. Bu, kısa basılı bir ifadeyi el yazısı bir işaretten
#: gerçekten ayıran özelliktir -- vuruş genişliği varyansı ve taban çizgisi
#: düzensizliği tek başına kelime ölçeğinde de eşiklerini geçer (sıradan
#: basılı bir kelimenin çıkıntı/inen harf karışımı ve değişen harf
#: genişlikleri yeterlidir). Basılı metin, tek bir kelime bile olsa, her
#: biri arasında boşluk olan birkaç ayrı glifden oluşur -- satır başına
#: birçok kısa koşu. Bir imza veya el yazısı işaret tipik olarak bir veya
#: birkaç sürekli bağlı vuruştur -- genişliğine göre çok daha az, daha
#: uzun koşu. Bu modülün hedeflediği gerçek taranmış korpusa karşı
#: doğrulandı (datasets/resmi_yazisma/00_gelen_kaynaklar/cevap_yazisi/):
#: bir örnek sayfadaki gerçekten basılı her metin parçası >=1.26 skorladı,
#: elle inşa edilmiş bir el yazısı test şekli 1.0 skorladı.
#:
#: 1.5'ten 2.3'e yükseltildi: ocr_ground_truth.json'un elle etiketlediği 23
#: belgeye karşı ölçüldüğünde (bkz. scripts/evaluate_marks.py
#: --ground-truth), 1.5 imza recall'ını %50'ye düşürüyordu -- 16 gerçek
#: imzadan 8'i, tam olarak bu kapıda kaçırılıyordu. 6 bağımsız kaçırılan
#: belgenin (2 farklı imza sahibi, CY-003/010/011/014/033/050) gerçek imza
#: bölgesinin run_density'si 1.62-2.17 arasında ölçüldü -- 1.5 tabanı, bu
#: modülün kendi kalibrasyon örneğinden daha "bağlantılı" (birden çok
#: kesişen kalem vuruşu) gerçek imzaları sistematik olarak dışlıyordu.
#: 2.3'e yükseltmek recall'ı %94'e çıkarır (15/16), kesinlik 1.00'de kalır
#: (yeni yanlış pozitif yok) -- 23 belgenin tamamına karşı doğrulandı.
#: 2.4'e denendi (kalan tek kaçırmayı, CY-002'yi, run_density=2.33 ile
#: yakalamak için) ama CY-005'te (has_signature=false) yeni bir yanlış
#: pozitif açtı; kesinlik precision=0.94'e düşerdi. is_signed, yalnızca
#: eksik bir imzayı işaretleyen bir tavsiye kontrolünü besliyor (bkz.
#: check_required_fields) -- burada bir yanlış pozitif (imzasız bir belgeyi
#: imzalı sanmak) gerçek bir eksikliği gizler, bir yanlış negatif ise
#: yalnızca gereksiz bir inceleme istemine yol açar; bu asimetri nedeniyle
#: 2.3'te (kesinlik önceliği) kalındı, 2.4'e geçilmedi.
_MAX_STROKE_RUN_DENSITY = 2.3
#: Sayfa yüksekliğinin bu oranında veya altında imza şeklindeki bir bölge
#: bir imza olarak sınıflandırılır (RYUEHY m.17'nin bir tane koyduğu yer);
#: onun üzerindeki aynı şekil bunun yerine el yazısı bir not olarak
#: bildirilir. Kullanılan tek konumsal sinyal, ve kaba bir tanesi -- ikisi
#: de aynı temel mürekkep-şekil sınıfıdır.
#:
#: Başlangıçta 2/3 idi ("alt üçte bir"), bu modülün test edildiği her
#: gerçek imzayı dışlıyordu: bu korpusun mektupları, aksi halde boş bir
#: A4 sayfada kısa gövdeli yanıtlardır, bu yüzden imza gövde metninin
#: bittiği yere düşer -- bu korpustaki 12 onaylanmış gerçek imza üzerinde
#: 0.38-0.65 ölçüldü (bkz.
#: datasets/resmi_yazisma/ocr_ground_truth.json), sayfanın kelimenin tam
#: anlamıyla alt üçte biri değil. En düşük onaylanmış vakanın (0.38)
#: rahatça altında olan 0.35'e düşürüldü, orijinal etiketli örneğin
#: dışında o konumsal banttaki belgeleri özellikle kontrol ettikten sonra:
#: onlardan her biri (CY-006/023/028/034) de korpusun başka bir yerinde
#: zaten onaylanmış bir şablon üzerinde gerçek bir imza olduğu ortaya
#: çıktı, rastlantısal bir yanlış pozitif değil -- yani bu, orijinal
#: örneklemden seçilmiş bir eşik değil, aşırı uyumu kontrol etmek için
#: genişletilmiş korpus kanıtıdır.
_SIGNATURE_ZONE_START_FRACTION = 0.35


def detect_marks(image, page: int) -> list[DetectedMark]:
    """En iyi çaba: rasterize edilmiş bir sayfada imza-, mühür- ve el yazısı
    şeklindeki mürekkep bölgelerini bul.

    Asla exception fırlatmaz -- bir dedektör hatası bir belge yüklemesini
    asla başarısız kılmamalıdır. Eksik `numpy`/`Pillow` (bu pakette diğer
    her çıkarıcıyla eşleşen korumalı import'lar), diğer herhangi bir
    başarısızlıkla aynı biçimde hiçbir şey bildirmeye düşer.

    Args:
        image: Örneğin OCR zincirinin `raster_cache`'inden gelen rasterize
            edilmiş bir PIL sayfa görüntüsü (bkz.
            `BaseDocumentExtractor.extract`).
        page: Döndürülen her işarete kaydedilen 1 tabanlı sayfa numarası.

    Returns:
        Tespit edilen işaretler, ya da herhangi bir başarısızlıkta veya
        yukarıdaki boyut/şekil eşiklerinden hiçbiri geçilmediğinde boş liste.
    """
    if np is None or _PILImage is None:
        return []
    try:
        return _detect_marks(image, page)
    except Exception:
        logger.warning("Mark detection failed for page %d; reporting none.", page, exc_info=True)
        return []


def _detect_marks(image, page: int) -> list[DetectedMark]:
    """Korumasız gerçek implementasyon -- her çağıranın gerçekte aldığı
    try/except sınırı için `detect_marks`'a bakın."""
    gray = np.asarray(image.convert("L"))
    height, width = gray.shape
    if height < _GRID_CELL_PX or width < _GRID_CELL_PX:
        return []
    ink = gray < _INK_GRAY_THRESHOLD

    grid = _grid_ink_density(ink, _GRID_CELL_PX) >= _CELL_INK_THRESHOLD
    components = _connected_components(grid)

    marks: list[DetectedMark] = []
    for cells in components:
        if len(cells) < _MIN_COMPONENT_CELLS:
            continue

        row0 = min(r for r, _ in cells)
        row1 = max(r for r, _ in cells) + 1
        col0 = min(c for _, c in cells)
        col1 = max(c for _, c in cells) + 1
        x0, y0 = col0 * _GRID_CELL_PX, row0 * _GRID_CELL_PX
        x1, y1 = min(col1 * _GRID_CELL_PX, width), min(row1 * _GRID_CELL_PX, height)
        if (x1 - x0) > width * _MAX_MARK_WIDTH_FRACTION:
            continue

        region = ink[y0:y1, x0:x1]
        kind, confidence = _classify(region, y_center_fraction=(y0 + y1) / 2 / height)
        if kind is None:
            continue

        marks.append(
            DetectedMark(
                kind=kind,
                page=page,
                bbox=(
                    round(x0 / width * 1000),
                    round(y0 / height * 1000),
                    round(x1 / width * 1000),
                    round(y1 / height * 1000),
                ),
                confidence=confidence,
            )
        )
    return marks


def _grid_ink_density(ink, cell_px: int):
    """Tamamen vektörize edilmiş, `cell_px` x `cell_px` ızgara hücresi
    başına mürekkep oranı.

    Args:
        ink: Tam sayfa çözünürlüğünde ikili mürekkep maskesi (True = mürekkep).
        cell_px: Izgara hücresi kenar uzunluğu, piksel cinsinden.

    Returns:
        `(height // cell_px, width // cell_px)` şeklinde hücre başına
        mürekkep yoğunluğunun 2D dizisi.
    """
    height, width = ink.shape
    rows, cols = height // cell_px, width // cell_px
    # Tam sayıda hücreye kırp -- birkaç pikseli kalan kısmi bir art satır/
    # sütun dolgulamaya değmez.
    trimmed = ink[: rows * cell_px, : cols * cell_px]
    return trimmed.reshape(rows, cell_px, cols, cell_px).mean(axis=(1, 3))


def _connected_components(grid) -> list[list[tuple[int, int]]]:
    """Boolean bir ızgarada `True` hücrelerin 4-bağlantılı bileşenleri.

    `scipy.ndimage.label` değil, düz flood fill -- ızgaranın ölçeğinde
    doğru (bir sayfanın sahip olduğu milyonlarca piksel değil, on binlerce
    hücre), ki bu tam olarak tespitin sayfayı önce ızgaraladığı nedendir.
    Modül docstring'ine bakın.

    Args:
        grid: Boolean 2D dizi.

    Returns:
        Bileşen başına, bulunma sırasına göre bir `(row, col)` hücre
        koordinatları listesi.
    """
    visited = np.zeros_like(grid, dtype=bool)
    rows, cols = grid.shape
    components: list[list[tuple[int, int]]] = []

    for start_r in range(rows):
        for start_c in range(cols):
            if not grid[start_r, start_c] or visited[start_r, start_c]:
                continue
            component: list[tuple[int, int]] = []
            stack = [(start_r, start_c)]
            visited[start_r, start_c] = True
            while stack:
                r, c = stack.pop()
                component.append((r, c))
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if (
                        0 <= nr < rows
                        and 0 <= nc < cols
                        and grid[nr, nc]
                        and not visited[nr, nc]
                    ):
                        visited[nr, nc] = True
                        stack.append((nr, nc))
            components.append(component)
    return components


def _classify(region, y_center_fraction: float) -> tuple[Optional[str], float]:
    """Bir mürekkep bölgesini sezgisel olarak sınıflandır. Bilinçli olarak
    kaba -- buna neden bir doğruluk iddiası eklenmediği için modül
    docstring'ine bakın.

    Sıralı kontroller, ilk eşleşme kazanır:
      1. Kabaca kare/dairesel, makul yoğunlukta, en az
         `_STAMP_MIN_DIMENSION_PX` genişliğinde, VE birçok kısa mürekkep
         koşusundan oluşan (`_STAMP_MIN_RUN_DENSITY`) -> `stamp` (resmi
         bir mühür veya antetli kaşe incelikli sanat eseridir, birkaç
         kalem vuruşu değil). Koşu yoğunluğu kapısı burada özellikle
         önemlidir -- bu olmadan, kabaca kare ve yeterince yoğun olan
         gerçek bir imza (gerçek, ölçülmüş bir başarısızlık modu: bkz.
         `_STAMP_MIN_RUN_DENSITY`'nin kendi yorumu) gerçek bir mührün
         geçtiği aynı şekil testini geçer ve 2. kontrol hiç çalışmadan
         önce yakalanır. Boyut tabanı da hâlâ önemlidir: bu olmadan küçük
         yoğun bir kare -- basılı bir karakter, bir logo parçası -- aynı
         şekil testini geçerdi.
      2. Düzensiz vuruş genişliği VE taban çizgisi VE düşük koşu
         yoğunluğu (birçok ayrı glif yerine az sayıda sürekli vuruş --
         bkz. `_MAX_STROKE_RUN_DENSITY`; ilk ikisi tek başına yeterli
         değildir, kendi docstring'ine bakın), `_SIGNATURE_ZONE_START_FRACTION`
         sayfa yüksekliğinde veya altında -> `signature` (RYUEHY m.17'nin
         bir tane koyduğu yer -- bu korpusun kısa gövdeli mektuplarında
         bunun neden tam anlamıyla "alt üçte bir" olmadığı için bu
         sabitin kendi yorumuna bakın).
      3. Sayfanın başka bir yerindeki aynı şekil -> `handwriting` (bir
         not, elle yazılmış bir referans numarası, bir kenar notu).
      4. Başka her şey -> hiç işaret değil; bu, kendi bileşenini
         oluşturacak kadar küçük basılı bir kelime veya kısa metin
         parçasının nasıl göründüğüdür.

    Args:
        region: Bir bileşenin sınırlayıcı kutusuna kırpılmış mürekkep maskesi.
        y_center_fraction: Bileşenin dikey merkezinin sayfa yüksekliğinin
            bir oranı olarak (0.0 üst, 1.0 alt) -- kullanılan tek konumsal
            sinyal, ve yalnızca `signature`'ı `handwriting`'den ayırmak için.

    Returns:
        `(kind, confidence)`, ya da hiçbir şey uygun değilse `(None, 0.0)`.
    """
    height, width = region.shape
    if height == 0 or width == 0:
        return None, 0.0

    aspect_ratio = width / height
    ink_density = float(region.mean())
    run_density = _stroke_run_density(region)

    min_ratio, max_ratio = _STAMP_ASPECT_RATIO_RANGE
    if (
        min_ratio <= aspect_ratio <= max_ratio
        and ink_density >= _STAMP_MIN_INK_DENSITY
        and min(height, width) >= _STAMP_MIN_DIMENSION_PX
        and run_density >= _STAMP_MIN_RUN_DENSITY
    ):
        return "stamp", round(min(1.0, 0.4 + ink_density), 2)

    stroke_cv = _stroke_width_cv(region)
    baseline_std = _baseline_std(region)
    if (
        stroke_cv >= _HANDWRITING_MIN_STROKE_CV
        and baseline_std >= _HANDWRITING_MIN_BASELINE_STD
        and run_density <= _MAX_STROKE_RUN_DENSITY
    ):
        confidence = round(min(1.0, 0.3 + stroke_cv / 2), 2)
        if y_center_fraction >= _SIGNATURE_ZONE_START_FRACTION:
            return "signature", confidence
        return "handwriting", confidence

    return None, 0.0


def _horizontal_runs(region) -> list[list[int]]:
    """Her boş olmayan satırdaki ardışık mürekkep koşularının uzunlukları.

    Hem `_stroke_width_cv` (her koşunun uzunluğunu düzleştirir) hem de
    `_stroke_run_density` (satır başına koşu sayar) tarafından paylaşılan
    tarama -- aynı temel yapı üzerinde iki ayrı soru, iki ayrı tarama değil.

    Args:
        region: Zaten tek bir bileşene kırpılmış ikili mürekkep maskesi.

    Returns:
        Herhangi bir mürekkep taşıyan satır başına bir koşu uzunlukları
        listesi; hiç mürekkebi olmayan satırlar boş bir liste olarak değil,
        tamamen atlanır.
    """
    rows_of_runs: list[list[int]] = []
    for row in region:
        runs: list[int] = []
        count = 0
        for pixel in row:
            if pixel:
                count += 1
            elif count:
                runs.append(count)
                count = 0
        if count:
            runs.append(count)
        if runs:
            rows_of_runs.append(runs)
    return rows_of_runs


def _stroke_width_cv(region) -> float:
    """Yatay mürekkep koşu uzunluklarının varyasyon katsayısı.

    Belirli bir yazı tipi boyutundaki basılı glifler oldukça tutarlı bir
    vuruş genişliğine sahiptir; el yazısı mürekkep kalem basıncı ve açısıyla
    değişir. Ölçekten bağımsızdır (ortalama üzerinden standart sapma), bu
    yüzden sayfanın DPI'sini bilmesine gerek yoktur. Tek başına bu, kısa
    basılı bir ifadeyi el yazısı bir işaretten ayırmaz -- bunu yapan
    `_stroke_run_density`'ye bakın; `_classify`'da ikisi birlikte gereklidir.

    Args:
        region: Zaten tek bir bileşene kırpılmış ikili mürekkep maskesi.

    Returns:
        Karşılaştırılacak ikiden az koşu varsa (değişecek bir şey yoksa) 0.0.
    """
    run_lengths = [length for runs in _horizontal_runs(region) for length in runs]
    if len(run_lengths) < 2:
        return 0.0
    arr = np.asarray(run_lengths, dtype=float)
    mean = arr.mean()
    return float(arr.std() / mean) if mean > 0 else 0.0


def _stroke_run_density(region) -> float:
    """Bölge genişliğinin 100px'i başına ortalama ayrı yatay mürekkep koşusu sayısı.

    Tam gerekçe için `_MAX_STROKE_RUN_DENSITY`'ye bakın: kelime ölçeğinde
    vuruş genişliği varyansı ve taban çizgisi düzensizliği tek başına
    yapamadığı halde, kısa basılı bir ifadeyi el yazısı bir işaretten
    gerçekten ayırt eden özellik budur.

    Args:
        region: Zaten tek bir bileşene kırpılmış ikili mürekkep maskesi.

    Returns:
        Hiç mürekkebi olmayan bir bölge için 0.0.
    """
    width = region.shape[1]
    if width == 0:
        return 0.0
    rows_of_runs = _horizontal_runs(region)
    if not rows_of_runs:
        return 0.0
    mean_runs = sum(len(runs) for runs in rows_of_runs) / len(rows_of_runs)
    return mean_runs / (width / 100)


def _baseline_std(region) -> float:
    """Sütunlar arasında en üstteki mürekkep pikselinin normalize edilmiş değişkenliği.

    Paylaşılan bir taban çizgisi üzerinde oturan basılı metin, sütundan
    sütuna oldukça sabit bir glif-üstü konumuna sahiptir; el yazısı veya
    başka türlü düzensiz mürekkep sahip değildir. Bileşen boyutları arasında
    karşılaştırılabilir olması için bölge yüksekliğine göre normalize edilir.

    Args:
        region: Zaten tek bir bileşene kırpılmış ikili mürekkep maskesi.

    Returns:
        İkiden az sütunda mürekkep varsa 0.0.
    """
    height = region.shape[0]
    if height == 0:
        return 0.0
    tops = []
    for col in region.T:
        rows_with_ink = np.flatnonzero(col)
        if rows_with_ink.size:
            tops.append(rows_with_ink[0])
    if len(tops) < 2:
        return 0.0
    return float(np.std(tops) / height)
