"""Bir taslağın karşılaştırıldığı değerler için tür-duyarlı kanonik biçimler.

``draft_verifier``, taslaktaki somut bir iddianın dayanaklı olup olmadığına,
her iki tarafı da küçük harf ASCII'ye katlayıp birinin diğerini içerip
içermediğini sorarak karar verir. Bu, metin için işe yarar ama *tipli*
değerler için başarısız olur, çünkü aynı gerçeğin iki farklı yazılışı
farklı dizelere katlanır:

    kaynak: "01.03.2026"      taslak: "1 Mart 2026"
    kaynak: "Madde 11"        taslak: "m. 11"
    kaynak: "125.000,00 TL"   taslak: "125.000 TL"
    kaynak: "E-44444444-841-77"  taslak: "E-44444444/841/77"

Ölçülen temel çizgi (``evaluation/reports/all-baseline.md``) bunun varsayımsal
olmadığını gösteriyor: deterministik taslak kapısının ürettiği her yanlış
pozitif bunlardan biri ve her biri doğru bir taslağa bir insan-döngüde
kesintiye mal oluyor. Token-örtüşme yedek yöntemi de bunları kurtaramaz --
"12 Mart 2026", kısa tokenlar atıldıktan sonra "12 03 2026" ile sadece yılı
paylaşır, bu da 0.75 eşiğine karşı 0.5 örtüşmedir.

Bu yüzden her tür bir kanonik biçim alır ve değerler bu biçim üzerinden
karşılaştırılır. Bu *kayıpsız normalleştirmedir, bulanık eşleştirme değil*:
kanonik bir biçim bir değerin nasıl yazıldığını değiştirir, asla ne anlama
geldiğini değiştirmez. İki farklı tarih asla tek bir kanonik dizeye
çökmemelidir; ay tablosunun tam (exact) olmasının ve ayrıştırılamayan bir
değerin en iyi tahmin yerine None döndürmesinin (metinsel karşılaştırmaya
geri dönmek için) nedeni budur.

Kasıtlı olarak dışlanan: anlamsal herhangi bir şey. Sayılar, tarihler ve
tutarlar eşitlik gerektirir, benzerlik değil -- "12.03.2026" ve
"13.03.2026" bir karakter farklıdır ve tamamen farklı şeyler ifade eder.
"""

import re
import unicodedata
from typing import Optional

__all__ = [
    "canonical_date",
    "canonical_document_number",
    "canonical_amount",
    "canonical_legislation",
    "canonical_for_kind",
]

#: Mevzuatın yazdığı şekliyle Türkçe ay adları, ASCII'ye katlanmış.
_MONTHS: dict[str, int] = {
    "ocak": 1,
    "subat": 2,
    "mart": 3,
    "nisan": 4,
    "mayis": 5,
    "haziran": 6,
    "temmuz": 7,
    "agustos": 8,
    "eylul": 9,
    "ekim": 10,
    "kasim": 11,
    "aralik": 12,
}

_TURKISH_MAP = str.maketrans(
    {
        "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i",
        "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
    }
)

_NUMERIC_DATE = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$")
#: ISO 8601 ("2026-04-09") -- bir kaynak belgenin kendi çıkarılmış metni
#: (örneğin bir PDF'in tam olarak "Dates: 2026-04-09 to 2026-05-06" yazması),
#: _NUMERIC_DATE'in ele aldığı Türkçe GG.AA.YYYY biçimi kadar sık bu biçimi
#: kullanır. Ondan önce kontrol edilir: baştaki 4 haneli bir grup asla
#: _NUMERIC_DATE'in ilk (1-2 haneli) gün grubuyla eşleşemez, yani iki kalıp
#: hiçbir zaman aynı girdi için yarışmaz, ama bunu önce sıralamak "en özgülü
#: önce" okumasını korur.
_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_TEXTUAL_DATE = re.compile(r"^(\d{1,2})\s+([a-z]+)\s+(\d{4})$")

#: "4982 sayılı" -> kanunun numarası.
_LAW_NUMBER = re.compile(r"^(\d{3,5})\s+sayili$")
#: "madde 12" / "m. 7" / "m.7" -> madde numarası.
_ARTICLE = re.compile(r"^(?:madde|m)\s*\.?\s*(\d+)$")

#: Korpüsün kullandığı biçimlerin herhangi birinde yazılmış bir para birimi.
_CURRENCY_ALIASES = {
    "tl": "TRY",
    "try": "TRY",
    "lira": "TRY",
    "euro": "EUR",
    "eur": "EUR",
    "usd": "USD",
    "dolar": "USD",
}
_AMOUNT = re.compile(r"^([\d.,\s]+?)\s*(tl|try|lira|euro|eur|usd|dolar)$")

#: Para birimi sembolleri ASCII katlaması tarafından doğrudan atılır, bu
#: yüzden yukarıdaki alternasyonda listelenmek yerine -- ki orada asla
#: eşleşemezlerdi -- katlamadan önce yazıyla ifade edilirler.
_CURRENCY_SYMBOLS = {"₺": " tl", "€": " eur", "$": " usd"}


def _fold(text: str) -> str:
    """Noktalama işaretlerini koruyarak, boşlukları sıkıştırıp küçük harf ASCII'ye katla."""
    folded = (text or "").translate(_TURKISH_MAP)
    decomposed = unicodedata.normalize("NFKD", folded)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", ascii_text).strip()


def canonical_date(value: str) -> Optional[str]:
    """Bir Türkçe tarihi ISO biçiminde ifade et.

    Mevzuatın, taslaklarının ve yüklenen bir belgenin kendi çıkarılmış
    metninin fiilen kullandığı biçimleri ele alır -- ``12.03.2026`` (ayrıca
    ``/`` veya ``-`` ile), ``12 Mart 2026`` ve ISO 8601'in ``2026-03-12``'si.

    Args:
        value: Yazıldığı şekliyle tarih.

    Returns:
        ``YYYY-MM-DD``, veya değer bunun anladığı bir tarih değilse None.
        None kasıtlıdır: tanınmayan bir değer yanlış bir kanonik biçime
        zorlanmak yerine metinsel karşılaştırmaya geri dönmelidir.
    """
    folded = _fold(value)

    match = _ISO_DATE.match(folded)
    if match:
        year, month, day = (int(part) for part in match.groups())
    else:
        match = _NUMERIC_DATE.match(folded)
        if match:
            day, month, year = (int(part) for part in match.groups())
        else:
            match = _TEXTUAL_DATE.match(folded)
            if not match:
                return None
            day_text, month_name, year_text = match.groups()
            if month_name not in _MONTHS:
                return None
            day, month, year = int(day_text), _MONTHS[month_name], int(year_text)

    # İmkansız tarihleri normalleştirmek yerine reddet; "32.13.2026" iddia
    # eden bir taslak, doğrulayıcının yine de dayanaksız olarak göstermesi
    # gereken bir kusurdur.
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def canonical_document_number(value: str) -> Optional[str]:
    """Resmi bir belge numarasındaki ayraç varyasyonunu kaldır.

    ``E-44444444-841-77``, ``E-44444444/841/77`` ve ``E 44444444 841 77``,
    aynı numaranın üç farklı yazılışıdır. Sadece alfanümerik dizi
    önemlidir.

    Args:
        value: Yazıldığı şekliyle belge numarası.

    Returns:
        Ayraçsız biçim, veya değer hiç rakam taşımıyorsa None (bu durumda
        bu bir belge numarası değildir ve öyle muamele görmemelidir).
    """
    folded = _fold(value)
    stripped = re.sub(r"[^a-z0-9]+", "", folded)
    if not stripped or not any(char.isdigit() for char in stripped):
        return None
    return stripped


def canonical_amount(value: str) -> Optional[str]:
    """Bir parasal tutarı ondalık artı ISO-benzeri bir para birimi kodu
    olarak ifade et.

    Türkçe gösterim binler için ``.``, ondalıklar için ``,`` kullanır, bu
    yüzden ``125.000,00 TL``, ``125.000 TL`` ve ``125000 TL`` aynı tutardır.
    Sondaki sıfır ondalıklar atılır, böylece ilk ikisi eşit karşılaştırılır.

    Args:
        value: Yazıldığı şekliyle tutar.

    Returns:
        ``"<tutar> <PARA_BİRİMİ>"``, veya değer tanınan bir tutar değilse
        None.
    """
    spelled = value or ""
    for symbol, word in _CURRENCY_SYMBOLS.items():
        spelled = spelled.replace(symbol, word)

    match = _AMOUNT.match(_fold(spelled))
    if not match:
        return None

    digits, currency = match.groups()
    digits = re.sub(r"\s+", "", digits)

    if "," in digits:
        whole, _, fraction = digits.rpartition(",")
        whole = whole.replace(".", "")
        fraction = fraction.rstrip("0")
    else:
        whole, fraction = digits.replace(".", ""), ""

    whole = whole.lstrip("0") or "0"
    if not whole.isdigit() or (fraction and not fraction.isdigit()):
        return None

    normalized = f"{whole}.{fraction}" if fraction else whole
    return f"{normalized} {_CURRENCY_ALIASES[currency]}"


def canonical_legislation(value: str) -> Optional[str]:
    """Bir mevzuat atfını iki kanonik biçimden biriyle ifade et.

    ``4982 sayılı``, ``kanun:4982`` olur; ``madde 11``, ``m. 11`` ve
    ``m.11`` hepsi ``madde:11`` olur. İkisi ayrı ad alanları olarak
    tutulur çünkü bir kanun numarası ile bir madde numarası farklı
    gerçeklerdir ve bir şeyin 4982. maddesine atıf yapan bir taslak, 4982
    sayılı kanundan bahseden bir kaynakla dayanaklandırılmış olmaz.

    Args:
        value: Yazıldığı şekliyle atıf.

    Returns:
        Kanonik atıf, veya değer bir atıf değilse None.
    """
    folded = _fold(value).rstrip(".")

    match = _LAW_NUMBER.match(folded)
    if match:
        return f"kanun:{int(match.group(1))}"

    match = _ARTICLE.match(folded)
    if match:
        return f"madde:{int(match.group(1))}"

    return None


#: İddia türü -> kanonikleştirici. ``draft_verifier``'ın zaten kullandığı
#: tür etiketleriyle anahtarlanmıştır, böylece ikisi sessizce birbirinden
#: sapamaz.
_BY_KIND = {
    "tarih": canonical_date,
    "sayı": canonical_document_number,
    "tutar": canonical_amount,
    "mevzuat": canonical_legislation,
}


def canonical_for_kind(kind: str, value: str) -> Optional[str]:
    """Bir değeri iddia türüne göre kanonikleştir.

    Args:
        kind: İddia türü (``tarih``, ``sayı``, ``tutar``, ``mevzuat``).
        value: Yazıldığı şekliyle değer.

    Returns:
        Kanonik biçim, veya türün bir kanonikleştiricisi yoksa (özellikle
        adların metinsel olarak karşılaştırıldığı ``kurum``) ya da değer
        ayrıştırılamıyorsa None.
    """
    canonicalise = _BY_KIND.get(kind)
    return canonicalise(value) if canonicalise else None
