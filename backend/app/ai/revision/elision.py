"""Gerçek içeriği kelimesi kelimesine yeniden üretmek yerine atlayan veya
düşüren bir reviser yanıtını tespit eder.

``app.ai.workflows.revise_graph``'ın modül docstring'i bir "yapısal
kayma-yok garantisi" belirtir: dokunulmamış metin asla model tarafından
yeniden üretilmez. Bu garanti aslında yalnızca çok-direktifli yolda geçerlidir;
orada her yeniden yazım, ``app.ai.revision.instruction._merge`` ile orijinal
taslağa karşı geri eklenir (splice). İki başka yol modelin ham çıktısını
eklemesiz (unspliced) olarak aktarır:

* Talimatın hedef aralığı bulunamadığında (``rewrite_node``'un
  ``target is None`` dalı), bütün-taslak bir yeniden yazım.
* Her onarım döngüsü geçişi (``rewrite_node``'un ``is_repair`` dalı) --
  reviser, yalnızca listelenmiş kusurları düzelterek önceki taslağın
  tamamını yeniden üretmesi istenir.

Her iki prompt da modele değiştirmesi istenmeyen şeyi korumasını söyler, ama
ne prompt ne de aşağı akıştaki hiçbir şey daha önce bunu gerçekten yapıp
yapmadığını kontrol etmiyordu. "Gerisini kelimesi kelimesine yeniden üret"
denilen daha küçük/hızlı bir model, değişmediğine karar verdiği bir paragraf
yerine tembelce bir üç nokta veya köşeli parantezli bir not koymak için iyi
bilinen bir kurulumdur -- kullanıcının (veya önceki bir turun) zaten
doldurmuş olduğu gerçek içeriği sessizce siler.

Bu modül, ``app.ai.verification.draft_verifier``'ın diğer kontrolleriyle
aynı şekilde bunu yakalayan deterministik kontroldür: ücretsiz, tekrarlanabilir,
regex/uzunluk tabanlı; ikinci bir onarım döngüsü icat etmek yerine var olan
sınırlı onarım döngüsüne bir ``RepairItem`` besler.
"""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from app.ai.workflows.intent_scorer import _compile_surface, normalize

#: Bütün bir taslağı yeniden üreten bir model, bazen "değişmedi" diye
#: hükmettiği bir bölüm için, onu yeniden üretmek yerine bir kısayol alır --
#: bir üç nokta veya gerçek içeriğin yerine geçen köşeli/normal parantezli
#: bir not. Resmî Türkçe yazışma meşru olarak bunların hiçbirini içermez
#: (bunlar, eksik olanı adlandıran, "gerisi"ne işaret etmeyen sistemin kendi
#: ``[BİLGİ EKSİK: ...]`` eksik-bilgi yer tutucu sözdiziminden farklıdır), bu
#: yüzden bir eşleşme, korunması gereken bir yanlış pozitif değil, atlamanın
#: kesin kanıtıdır.
_ELISION_MARKERS = re.compile(
    r"(\.{3,}|…|"
    r"\[(?:de[gğ]i[sş]medi|ayn[ıi]|i[cç]erik ayn[ıi]|de[gğ]i[sş]iklik yok)\]|"
    r"\((?:de[gğ]i[sş]medi|ayn[ıi]|i[cç]erik ayn[ıi] kald[ıi]|k[ıi]salt[ıi]ld[ıi])\))",
    re.IGNORECASE,
)

#: Meşru olarak daha kısa bir taslak isteyen talimat anahtar kelimeleri --
#: bunlardan biri altında büyük bir uzunluk düşüşü, içerik kaybı değil
#: kullanıcının kendi isteğidir. Uzunluk/özet olanların yanında açık
#: silme/kaldırma fiillerini içerir ("sil", "cikar", "kaldir", "temizle",
#: "azalt", "indir"): reviser'ın gerçekten yerine getirdiği bir "şu
#: paragraftan bir kısmı sil" isteği, asla bir atlama kusuru olarak
#: işaretlenip modele "zaten doldurulmuş" içeriği geri getirmesini söyleyen
#: kendi promptu olan bir onarım geçişine geri döngülenmemelidir -- bu,
#: kullanıcının istediği silmeyi sessizce geri alırdı. Düz bir alt dize
#: testi değil (C10), ``ALL_RULES``'ın kullandığı aynı
#: ``intent_scorer._compile_surface`` derleyicisi üzerinden sol kelime
#: sınırıyla eşleştirilir: "Asıl metni koru", "asil metni koru"ya katlanır;
#: bu "asil" içinde alt dize olarak "sil"i içerir ve yalnızca bu tesadüften
#: dolayı bir silme isteği olarak yanlış ateşlenirdi.
_SHORTENING_SURFACES: tuple[str, ...] = (
    "kisalt", "ozetle", "sadelestir", "daha kisa", "kucult", "sil", "cikar",
    "kaldir", "temizle", "azalt", "indir",
)
_SHORTENING_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    _compile_surface(surface) for surface in _SHORTENING_SURFACES
)

#: Bir kısaltma yüzeyinden hemen önce bulunduğunda anlamını tersine çeviren
#: olumsuzlama kelimeleri -- "Hiçbir yeri kısaltma", "kisalt" içerir ama
#: hiçbir şeyi kısaltma*ma*ya dair açık bir talimattır; niteliksiz bir alt
#: dize eşleşmesinin öne süreceğinin tersi (C10).
_NEGATION_MARKERS = ("hicbir", "hic ", "asla", "sakin", "yapma", "etme")

#: Bir kısaltma-yüzeyi eşleşmesinden önce bir olumsuzlama işareti için
#: taranacak katlanmış karakter sayısı -- "Hiçbir yeri kısaltma"yı
#: ("kisaltma"dan önceki "hicbir yeri "nin ~15 karakteri) ilgisiz daha önceki
#: bir cümleye kadar geri gitmeden kapsamaya yeter.
_NEGATION_WINDOW = 20


def _wants_shorter(instructions: str) -> bool:
    """Talimatın daha kısa/kırpılmış bir taslak isteyip istemediği.

    Args:
        instructions: Kullanıcının revizyon talimatı.

    Returns:
        Hemen öncesinde bir olumsuzlama işareti olmayan (bkz.
        ``_NEGATION_MARKERS``) bulunan ilk kısaltma yüzeyi için True.
    """
    normalized = normalize(instructions)
    for pattern in _SHORTENING_PATTERNS:
        for match in pattern.finditer(normalized):
            window = normalized[max(0, match.start() - _NEGATION_WINDOW) : match.start()]
            if any(marker in window for marker in _NEGATION_MARKERS):
                continue
            return True
    return False


def _new_elision_markers(previous_draft: str, rewritten_draft: str) -> list[str]:
    """*Bu* yeniden yazım geçişinin tanıttığı atlama işaretleri, önceki
    taslağın zaten taşıdıkları değil.

    C11: ``_ELISION_MARKERS`` eskiden yalnızca ``rewritten_draft``'ta
    aranıyordu, bu yüzden zaten meşru olarak birini içeren bir taslak
    (kısmi bir atıf alıntılayan bir "İlgi:" satırı, tesadüfen "..." kullanan
    bir korpus yer tutucusu) o satıra hiç dokunmayanlar dahil *sonraki her*
    revizyon geçişinde bu kontrolü geçemiyordu -- reviser onu doğru bir
    şekilde kelimesi kelimesine yeniden üretiyordu, tam olarak yapması
    gereken şey buydu, ve yine de işaretleniyordu.

    Args:
        previous_draft: Bu yeniden yazım geçişinden önceki taslak metni.
        rewritten_draft: Modelin bu geçiş için yeni çıktısı.

    Returns:
        İkisi arasında sayısı artan farklı işaret string'leri -- yeniden
        yazım zaten var olanın ötesinde hiçbir atlama tanıtmadıysa boş.
    """
    previous_counts = Counter(_ELISION_MARKERS.findall(previous_draft))
    rewritten_counts = Counter(_ELISION_MARKERS.findall(rewritten_draft))
    return [
        marker
        for marker, count in rewritten_counts.items()
        if count > previous_counts.get(marker, 0)
    ]


#: Ortada bir kısaltma talimatı yokken önceki taslağın uzunluğunun bu
#: oranının altında, bir yeniden yazımın gerçekten söyleyecek bu kadar az
#: şeyi kaldığı değil, sessizce içerik düşürdüğü varsayılır.
_MIN_LENGTH_RATIO = 0.6


@dataclass(frozen=True)
class ContentLossFinding:
    detail: str
    suggested_fix: str


def detect_content_loss(
    previous_draft: str, rewritten_draft: str, instructions: str
) -> Optional[ContentLossFinding]:
    """Yalnızca istenen değişikliği uygulamak yerine gerçek içeriği düşürmüş
    gibi görünen bir yeniden yazımı işaretler.

    Args:
        previous_draft: Bu yeniden yazım geçişinden önceki taslak metni
            (yeni bir revize turunda aktif taslak, veya bir onarım
            geçişinde son denemenin çıktısı).
        rewritten_draft: Modelin bu geçiş için yeni çıktısı.
        instructions: Kullanıcının revizyon talimatı; uzunluk-oranı kontrolü
            tetiklenmeden önce açık bir kısaltma isteği için kontrol edilir.

    Returns:
        Kaybolmuş görünen şeyi tanımlayan bir bulgu, ya da hiçbir şey
        kaybolmadıysa ``None``.
    """
    markers = _new_elision_markers(previous_draft, rewritten_draft)
    if markers:
        return ContentLossFinding(
            detail=(
                "Taslakta önceki içeriğin yerine kısaltma/atlama ifadesi "
                f"({', '.join(sorted(set(markers)))}) kullanılmış."
            ),
            suggested_fix=(
                "Talimatla ilgisiz her cümleyi önceki taslaktaki haliyle, "
                "kelimesi kelimesine ve eksiksiz olarak yeniden üret; hiçbir "
                "kısmı '...' veya benzeri bir ifadeyle atlama."
            ),
        )

    previous_length = len(previous_draft.strip())
    if previous_length == 0:
        return None
    rewritten_length = len(rewritten_draft.strip())
    wants_shorter = _wants_shorter(instructions)
    if not wants_shorter and rewritten_length < previous_length * _MIN_LENGTH_RATIO:
        percentage = round(rewritten_length / previous_length * 100)
        return ContentLossFinding(
            detail=(
                "Revize edilen taslak, talimatta kısaltma istenmediği halde "
                f"önceki taslağın yaklaşık %{percentage}'i uzunluğunda -- içerik "
                "kaybı olabilir."
            ),
            suggested_fix=(
                "Talimatla ilgisiz olan tüm cümle ve paragrafları önceki "
                "taslaktaki haliyle, eksiksiz olarak koru; yalnızca istenen "
                "değişikliği uygula."
            ),
        )
    return None
