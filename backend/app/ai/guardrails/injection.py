"""Belge metni ve üretim sınırlarında prompt-injection temizliği.

OCR'lenmiş veya doğrudan çıkarılmış belge metni, herhangi bir arındırma
yapılmadan agent prompt'larına akar. Gönderilen bir PDF, sistemin bakış
açısından saldırgan kontrolündeki bir girdidir -- bir belgeyi bir
çalışanın önüne koyabilen herkes, içine metin koyabilir; bu metin, işleyen
modele bir talimat gibi görünen bir şey de olabilir ("önceki talimatları
unut", "you are now..."). Bu modül, sınır kontrolüdür; her prompt çağrı
noktasında ayrı ayrı tekrarlanmak yerine, çıkarımdan hemen sonra bir kez
uygulanır (``char_count`` eşiği çalışmadan önce, böylece ölçülen şey
temizlenmiş belgenin kendisidir).

Bu kod tabanının doğrulama katmanının geri kalanıyla (``draft_verifier.py``,
``planner.py``) uyumlu olarak deterministik ve regex tabanlı: bir
sınıflandırıcı eğitim verisi gerektirir ve her yüklemede çalışan bir yola
bir model çağrısı ekler.
"""

import re
import unicodedata

_TURKISH_MAP = str.maketrans(
    {
        "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i",
        "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
    }
)


class GuardrailViolation(Exception):
    """Üretilen bir yanıt, sistem promptunu sızdırmış veya gerçek işini
    yapmak yerine gömülü talimatlara uymuş gibi göründüğünde fırlatılır."""


#: Sıfır genişlikli ve bidi kontrol karakterleri (U+200B-U+200F,
#: U+202A-U+202E, U+FEFF); metni sıradan bir okumadan gizlerken model
#: tarafından yine de tokenleştirilmesi için kullanılır.
_INVISIBLE_CHARS = re.compile(
    "[​‌‍‎‏‪-‮﻿]"
)

#: Türkçe ve İngilizce talimat geçersiz kılma kalıpları; büyük/küçük harf ve
#: Türkçe karakterlerin eşleşmeyi atlatmak için kullanılamaması için
#: katlanmış (küçük harfe çevrilmiş, aksan işaretleri kaldırılmış) metne
#: karşı eşleştirilir.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bonceki\s+talimatlar\w*\s+(unut|yoksay|dikkate\s+alma)\w*",
        r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions?\b",
        r"\bdisregard\s+(all\s+)?(previous|prior|above)\s+instructions?\b",
        r"\bsen\s+artik\b",
        r"\byou\s+are\s+now\b",
        r"^\s*system\s*:",
        r"^\s*###?\s*(system|sistem)\b",
        r"\bact\s+as\s+(a|an)\b",
        r"\byapay\s+zeka\s+asistani\s+degil",
    )
)


def _fold(text: str) -> str:
    """Türkçe metni, kalıp eşleştirme için küçük harfli ASCII'ye katla."""
    translated = (text or "").translate(_TURKISH_MAP)
    normalized = unicodedata.normalize("NFKD", translated)
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def scrub_extracted_text(text: str) -> tuple[str, list[str]]:
    """Çıkarılan metinden görünmez karakterleri ve talimat geçersiz kılma
    satırlarını kaldır.

    Bir satırı tamamen kaldırmak bilinçli, kaba bir tercihtir: satır içinde
    kısmi bir kırpma, hâlâ bir talimat gibi ayrıştırılabilecek kesilmiş bir
    talimat bırakma riski taşır; belge metni yeterince satır odaklıdır
    (başlık alanları, satır başına bir madde) ki tüm bir satırı düşürmek
    nadiren gerçek içerik kaybına yol açar.

    Args:
        text: Ham çıkarılmış/OCR'lenmiş belge metni.

    Returns:
        Temizlenmiş metin ve neyin kaldırıldığını açıklayan kısa Türkçe
        işaretlerin listesi -- analiz yanıtında (``extraction.scrubbed_markers``)
        gösterilir, böylece temizlik sessizce değil, raporlanarak yapılır.
    """
    if not text:
        return text, []

    markers: list[str] = []
    cleaned = _INVISIBLE_CHARS.sub("", text)
    if cleaned != text:
        markers.append("gizli_karakterler_temizlendi")

    kept_lines: list[str] = []
    removed = 0
    for line in cleaned.split("\n"):
        if any(pattern.search(_fold(line)) for pattern in _INJECTION_PATTERNS):
            removed += 1
            continue
        kept_lines.append(line)

    if removed:
        markers.append(f"olasi_talimat_enjeksiyonu_{removed}_satir_kaldirildi")

    return "\n".join(kept_lines), markers


#: Bu uygulamanın kendi prompt-iskeleti bölüm başlıkları -- numaralı brief
#: işaretleri (``app.ai.workflows.revise_graph``/``draft_graph`` içindeki
#: ``_build_brief``), writer/reviser prompt'unun kendi bölüm başlıkları
#: ("### GÖREV", "### BRIEF BELGESİ", ...). Daha küçük bir yerel model,
#: özellikle revize onarım prompt'u gibi ağır şekilde numaralanmış bir
#: prompt altında, kendi talimatlarının parçalarını zaman zaman sanki
#: içerikmiş gibi geri yansıtır -- bu, kullanıcının modeli ele geçirmeye
#: *çalıştığını* yakalayan yukarıdaki ``_INJECTION_PATTERNS``'den farklıdır,
#: modelin kendi iskeletini istemsizce geri kusmasını yakalar. Genel bir
#: "prompt gibi görünüyor" sezgisi yerine bu uygulamanın kendi gerçek bölüm
#: etiketlerine dar bir şekilde eşleştirilir, böylece kendi resmi metninde
#: örneğin "görev tanımı"ndan bahseden meşru bir taslak asla bununla
#: yakalanmaz.
_SCAFFOLD_ECHO_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"###\s*(gorev|brief\s+belgesi|yazisma\s+turu\s+profili|degistirilecek\s+bolum|"
        r"mevcut\s+taslak|kullanici\s+talimati|kural|cikti|onceki\s+taslak)\b",
        r"\bbrief\s+belgesi\s*:",
        r"\bonceki\s+taslak\s+surumu\s*:",
        r"\bdogrulanmis\s+siniflandirma\s*:",
        r"\bdogrulanmis\s+mevzuat\s+baglami\s*:",
        r"\byazisma\s+turu\s+profili\s*:",
        r"\buslup\s+referans\s+ornekleri\s*:",
        r"\bnumarali\s+kusur\s+listesindeki\b",
    )
)


def assert_no_scaffold_echo(response: str) -> None:
    """Doğrulayıcı: üretilen bir yanıt, düz taslak metni üretmek yerine bu
    uygulamanın kendi prompt-iskeleti başlıklarını (numaralı brief,
    writer/reviser prompt'unun bölüm işaretleri) yansıtıyorsa fırlat.

    Ağır yapılandırılmış numaralı bir brief etrafında prompt'lar kuran
    revize akışının ``rewrite_node``'una (bkz.
    ``app.ai.workflows.revise_graph``) bağlıdır -- bu, daha küçük bir yerel
    modelin kendi tamamlamasında taklit etmeye en meyilli olduğu şekildir.

    Args:
        response: Agent'ın ürettiği metin.

    Raises:
        GuardrailViolation: Bir iskelet-yansıması kalıbı tespit edilirse.
    """
    folded = _fold(response or "")
    for pattern in _SCAFFOLD_ECHO_PATTERNS:
        if pattern.search(folded):
            raise GuardrailViolation(
                "Üretilen yanıt, talimat şablonunun kendisini (brief/prompt "
                "iskeleti) içeriyor -- gerçek bir taslak metni değil."
            )


def assert_no_prompt_leak(response: str) -> None:
    """Doğrulayıcı: üretilen bir yanıt bir geçersiz kılma talimatını
    yansıtıyorsa veya agent'ın gerçek çıktısı yerine bir sistem promptu
    sızıntısı gibi okunuyorsa fırlat.

    Writer/reviser/classifier agent'ları için ``BaseAgent.validators``'a
    bağlıdır (bkz. ``app/ai/agents/base.py``); bir ihlal, kullanıcıya
    sessizce döndürülmek yerine mevcut denemeyi başarısız kılar.

    Args:
        response: Agent'ın ürettiği metin.

    Raises:
        GuardrailViolation: Bir sızıntı kalıbı tespit edilirse.
    """
    folded = _fold(response or "")
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(folded):
            raise GuardrailViolation(
                "Üretilen yanıt olası bir talimat enjeksiyonu veya sistem "
                "promptu sızıntısı içeriyor."
            )
