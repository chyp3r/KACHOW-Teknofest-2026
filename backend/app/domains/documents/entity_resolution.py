"""Bilgi grafiğinin Entity düğümleri için saf (pure) entity-çözümleme
hattı (pipeline).

`resolve_entities`, bir evrakın `muhatap` / `gonderen_kurum` / `entities[]`
alanlarının tüm korpus genelinde ürettiği her ham yüzey-formu dizgesini alır
ve her birini bir `ResolvedEntity`'ye eşler -- ait olduğu kanonik düğüm,
okunabilir bir etiket, sezgisel bir tür ve o düğümde birleştirilen her yüzey
formu (böylece grafiğin düğüm inceleyicisi birleşmeyi gizlemek yerine ifşa
edebilir).

Bu modülün var olma nedeni: v1 bilgi grafiği (bkz. `knowledge_graph.py`'nin
kendi docstring'i) bilinçli olarak çıkarılan evrak metniyle anahtarlanan
herhangi bir düğümü dışladı, çünkü ham dizge kimliği OCR hasarını doğrudan
düğüm kimliğine taşır. Gerçek korpus üzerinde ölçüldüğünde, yalnızca
`muhatap` bile bir kurumun dört yüzey formunu taşıyor -- markdown başlık
kalıntısı, sızmış bir önerge numarası, temiz bir form ve gerçek bir OCR
yer değiştirmesi (Ğ'nin Ç olarak yanlış okunması) içeren bir form. Bu modül,
"düğüm kimliğindeki OCR hasarını" Kurum/Entity düğümlerini dışlama
gerekçesi olmaktan çıkarıp bunun yerine onları *çözme* gerekçesine dönüştürür.

Her ham dizgeye, kümelemeden önce bağımsız olarak uygulanan hat (pipeline):

1. Baştaki markdown/liste kalıntılarını temizle (`#####`, `*`, `>`, `-`).
2. Sondaki parantez içi ifadeleri temizle -- `(Kanunlar ve Kararlar
   Başkanlığı)`.
3. Sızmış 4+ haneli sayıları temizle -- dizgenin ortasına düşen bir önerge
   numarası.
4. `normalizers._fold`'u yeniden kullanarak Türkçe'ye duyarlı biçimde küçük
   harf ASCII'ye katla -- bilinçli olarak ikinci bir Türkçe büyük/küçük harf
   tablosu değil.
5. İsme sondaki bir belirteç olarak sızmış ivedilik işaretlerini temizle --
   `GÜNLÜDÜR` / `İVEDİ` / `ACELE` (ölçüldü: `CUMHURBAŞKANI YARDIMCISI
   GÜNLÜDÜR` ile `CUMHURBAŞKANI YARDIMCISI`, aynı makam).
6. Yalnızca *son* token'dan bir hal/yönelme eki temizle --
   `...BAŞKANLIĞINA` -> `...BAŞKANLIĞI`. Yalnızca iki harfli n-tamponlu
   yönelme eki (`-na`/`-ne`) ve y-tamponlu yönelme eki (`-ya`/`-ye`)
   temizlenir, üç harfli `-ina`/`-ine` varyantı temizlenmez: kelime zaten
   hal ekinin eklendiği iyelik `-ı`/`-i` ile bitiyor ve daha uzun varyantı
   kaldırmak o iyelik ünlüsünü de yerdi.

1-6. adımların düzeltemediği şey, kalıntı tek karakterlik OCR gürültüsüdür
(yukarıdaki örnekte Ğ<->Ç, iki *farklı* ASCII harfine, g ve c'ye katlanır --
bu bir harf katlama sorunu değil, gerçek bir yanlış okumadır). Bu kalıntı,
ham dizgeler üzerinde değil *kanonik* anahtarlar üzerinde deterministik bir
bulanık (fuzzy) geçişle yakalanır: anahtarları sırala, sonra
`difflib.SequenceMatcher` ile zaten üretilmiş küme temsilcilerine karşı
tek geçişli birleştirme (agglomeration) yap; temsilci = kümedeki sözlüksel
olarak en küçük anahtar. Önce sıralamak, kümelemenin girdi sırasından
bağımsız olmasını sağlar -- sıralanmamış girdi üzerinde düz açgözlü (greedy)
bir geçiş, grafiğin şeklini dict/list yineleme sırasına bağımlı kılardı; bu
da tam olarak bu grafiğin bir projektörde göze alamayacağı türden bir
belirsizliktir.
"""

from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional, Sequence

from app.ai.verification.normalizers import _fold

#: Çıkarım (extraction) sırasında bir isim alanına sızmış, kurumun isminin
#: kendisinin bir parçası olmayan ivedilik/yönlendirme belirteçleri olan
#: sondaki token'lar. Katlanmış token'larla karşılaştırıldıkları için zaten
#: katlanmış (küçük harf ASCII) haldedir.
_URGENCY_MARKERS = {"gunludur", "ivedi", "acele"}

#: Bu korpustaki kurum isimlerinin gerçekten taşıdığı iki harfli Türkçe
#: hal/yönelme ekleri (iyelik ünlüsünden sonra n-tamponu, diğer ünlülerden
#: sonra y-tamponu). Bilinçli olarak üç harfli "-ina"/"-ine" şeklini
#: dışlar -- nedeni için modül docstring'ine bakın.
_DATIVE_SUFFIXES = ("na", "ne", "ya", "ye")
_MIN_TOKEN_LENGTH_FOR_SUFFIX_STRIP = 6

#: Bu uzunluğun altında iki kanonik anahtar asla bulanık (fuzzy)
#: karşılaştırılmaz -- kısa dizgeler yapay olarak yüksek SequenceMatcher
#: oranları üretir (örn. "tbmm" ile "tbnm" arasında %75 uzunlukta tek
#: karakterlik bir fark vardır) ve gerçekten farklı iki kısa kurumu
#: birleştirme riski taşır.
_MIN_FUZZY_LENGTH = 8
_FUZZY_RATIO_THRESHOLD = 0.88

#: İsim içindeki konumdan bağımsız olarak bir kurumu işaret eden katlanmış
#: token'lar -- hem bulanık-birleştirmeye yakın sınıflandırıcıyı yönlendirmek
#: hem de yalnızca ek kontrolünün kaçıracağı çok kelimeli makamları
#: yakalamak için kullanılır (örn. "hukuk hizmetleri genel mudurlugu").
_INSTITUTION_TOKENS = {
    "bakanligi", "bakanlik", "baskanligi", "baskanlik", "mudurlugu", "mudurluk",
    "komisyonu", "komisyon", "meclisi", "meclis", "kaymakamligi", "valiligi",
    "genel", "daire", "dairesi", "kurulu", "kurumu", "idaresi", "sayistay",
    "tbmm", "nato", "mnc", "btk", "yerlerine",
}


@dataclass(frozen=True)
class ResolvedEntity:
    """Tek bir çözülmüş Entity düğümü: grafik oluşturucunun ve frontend'in
    düğüm inceleyicisinin ihtiyaç duyduğu her şey."""

    key: str
    label: str
    kind: str  # "kurum" | "kisi" | "diger"
    surface_forms: tuple[str, ...]


def _strip_dative_suffix(token: str) -> str:
    if len(token) < _MIN_TOKEN_LENGTH_FOR_SUFFIX_STRIP:
        return token
    for suffix in _DATIVE_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def _canonicalize_single(raw: Optional[str]) -> Optional[str]:
    """Modül docstring'indeki hattın 1-6 adımları, tek bir dizgeye uygulanır."""
    if not raw:
        return None
    text = raw.strip()
    text = text.lstrip("#*>- \t")
    # Sondaki parantez içi ifade(ler), başında boşluk olabilir.
    while "(" in text and text.rstrip().endswith(")"):
        open_index = text.rfind("(")
        if open_index == -1:
            break
        text = text[:open_index].rstrip()
    # Sızmış 4+ haneli sayılar (dizgenin ortasındaki bir evrak numarası).
    text = "".join(
        part if not (part.isdigit() and len(part) >= 4) else " "
        for part in _split_keep_digits(text)
    )
    folded = _fold(text)
    if not folded:
        return None
    tokens = [t for t in folded.split(" ") if t]
    while tokens and tokens[-1] in _URGENCY_MARKERS:
        tokens.pop()
    if not tokens:
        return None
    tokens[-1] = _strip_dative_suffix(tokens[-1])
    canonical = " ".join(t for t in tokens if t)
    return canonical or None


def _split_keep_digits(text: str) -> list[str]:
    """Rakam ve rakam olmayan çalışmalara (run) böler, örn. 'a 741393 b' ->
    ['a ', '741393', ' b'] -- çağıranın yalnızca sızmış bir evrak/önerge
    numarası olacak kadar uzun rakam çalışmalarını boşaltmasını sağlar."""
    parts: list[str] = []
    current = []
    current_is_digit: Optional[bool] = None
    for ch in text:
        is_digit = ch.isdigit()
        if current_is_digit is None or is_digit == current_is_digit:
            current.append(ch)
        else:
            parts.append("".join(current))
            current = [ch]
        current_is_digit = is_digit
    if current:
        parts.append("".join(current))
    return parts


def _cluster_canonical_keys(keys: set[str]) -> dict[str, str]:
    """Her kanonik anahtarı küme temsilcisine eşler. Girdi sırasından
    bağımsız ve deterministiktir: anahtarlar kümelemeden önce sıralanır ve
    herhangi bir kümenin temsilcisi her zaman içindeki sözlüksel olarak en
    küçük anahtardır (o kümeyi başlatan, sıralamada ilk gelen anahtar)."""
    representatives: list[str] = []
    assignment: dict[str, str] = {}
    for key in sorted(keys):
        match = None
        if len(key) >= _MIN_FUZZY_LENGTH:
            for rep in representatives:
                if len(rep) < _MIN_FUZZY_LENGTH:
                    continue
                if SequenceMatcher(None, key, rep).ratio() >= _FUZZY_RATIO_THRESHOLD:
                    match = rep
                    break
        if match is None:
            representatives.append(key)
            assignment[key] = key
        else:
            assignment[key] = match
    return assignment


def _classify_kind(canonical_key: str, label: str) -> str:
    tokens = canonical_key.split(" ")
    if any(t in _INSTITUTION_TOKENS for t in tokens):
        return "kurum"
    if len(tokens) == 1 and len(canonical_key) <= 6:
        # Bilinen bir kurum kelimesiyle eşleşmeden çözümden kurtulan tek ve
        # kısa bir token neredeyse her zaman bir kısaltmadır (NATO, BTK) --
        # Türkçe kişi isimleri asla tek, tamamen büyük harfli bir token
        # olmaz, bu yüzden burayı "kisi" saymak daha yanıltıcı bir tahmin
        # olurdu.
        letters_only = "".join(ch for ch in label if ch.isalpha())
        if letters_only and letters_only == letters_only.upper():
            return "kurum"
    if len(tokens) > 3:
        return "kurum"
    label_tokens = [t for t in label.split(" ") if t]
    if 1 <= len(label_tokens) <= 3 and all(t[:1].isupper() for t in label_tokens):
        return "kisi"
    return "diger"


def resolve_entities(raw_names: Sequence[Optional[str]]) -> dict[str, "ResolvedEntity"]:
    """Her ham yüzey-formu dizgesini paylaşılan `ResolvedEntity`'sine çözer.

    Args:
        raw_names: Kapsamdaki her evrakın `muhatap` / `gonderen_kurum` /
            `entities[]` alanının ürettiği her ham dizge -- yinelemeler
            beklenir ve anlamlıdır ("en sık geçen yüzey formu" etiket
            seçimini bunlar yönlendirir).

    Returns:
        Girdideki her *farklı, boş olmayan* ham dizgeyi, kümesinin
        çözüldüğü `ResolvedEntity`'ye eşleyen bir eşleme. Birleşen iki ham
        dizge, aynı `ResolvedEntity`'yi paylaşır (dataclass eşitliği, yalnız
        aynı `key` değil). Boş/`None`/yalnızca boşluk içeren girdiler
        eşlenmez, atlanır.
    """
    canonical_by_raw: dict[str, str] = {}
    for raw in raw_names:
        if raw is None:
            continue
        canonical = _canonicalize_single(raw)
        if canonical:
            canonical_by_raw[raw] = canonical

    if not canonical_by_raw:
        return {}

    unique_canonical = set(canonical_by_raw.values())
    cluster_of = _cluster_canonical_keys(unique_canonical)

    raw_counts = Counter(raw for raw in raw_names if raw in canonical_by_raw)

    forms_by_representative: dict[str, dict[str, int]] = {}
    for raw, canonical in canonical_by_raw.items():
        representative = cluster_of[canonical]
        forms_by_representative.setdefault(representative, {})[raw] = raw_counts[raw]

    result: dict[str, ResolvedEntity] = {}
    for representative, forms in forms_by_representative.items():
        raw_label = sorted(forms.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        # Gerçek korpus üzerinde ölçüldü: markdown önekli bir yüzey formu
        # meşru şekilde *en sık geçen* olabilir (burada 11 geçişten 5'i,
        # temiz formda ise 4) -- "en sık geçen kazanır" kuralı aksi halde
        # bir jürinin önündeki grafik düğümüne "##### TÜRKİYE ...
        # BAŞKANLIĞINA" yazardı. Görüntü için yalnızca baştaki markdown
        # gürültüsü temizlenir; sondaki bir parantez içi ifade gerçek bir
        # bilgidir (örn. bir alt birim) ve korunur. Aşağıdaki
        # `surface_forms` yine de ham, temizlenmemiş formu ifşa eder --
        # bu yalnızca kozmetiktir, ikinci bir kanonikleştirme değildir.
        label = raw_label.lstrip("#*>- \t") or raw_label
        surface_forms = tuple(sorted(forms))
        kind = _classify_kind(representative, label)
        entity = ResolvedEntity(key=representative, label=label, kind=kind, surface_forms=surface_forms)
        for raw in forms:
            result[raw] = entity

    return result
