"""Çıkarılan belge metni üzerinde deterministik Türkçe PII tespiti.

``app.ai.compliance.field_parser``'ın regex-öncelikli yaklaşımıyla aynı
gerekçe (modül docstring'ine bakın): bir TCKN veya IBAN, bir modelin
çıkarım yapması gereken serbest biçimli bir gerçek değil, checksum'lı
yapısal olarak tanımlanmış bir değerdir -- her yüklemede ve guardrail
tarafından taranan her yanıtta çalışan bir yol için regex artı gerçek
checksum algoritması, bir model çağrısından hem daha hızlı hem de daha
doğrudur. Bir bulgu yalnızca maskelenmiş bir önizleme taşır, asla ham
değeri taşımaz; böylece bir PII bulgusu, işaretlediği PII'nin kendisi
ikinci bir şifrelenmemiş kopyası haline gelmez (loglarda,
``GuardrailEventModel.reasons``'da veya gittiği herhangi bir yerde).
"""

import re
from typing import Optional

from pydantic import BaseModel, Field

#: Türkiye Cumhuriyeti kimlik numarası: tam olarak 11 hane, daha uzun bir
#: dizinin alt dizesi değil (belge numarası gibi "12345678901234" eşleşmemeli).
_TCKN_PATTERN = re.compile(r"(?<!\d)\d{11}(?!\d)")

#: Türk IBAN'ı: "TR" + 24 hane, bankaların bastığı gibi isteğe bağlı boşluk
#: gruplu.
_IBAN_PATTERN = re.compile(
    r"\bTR\d{2}(?:[ ]?\d{4}){5}[ ]?\d{2}\b", re.IGNORECASE
)

#: Türk telefon numaraları: isteğe bağlı +90/0 öneki, mobil (5xx) veya sabit
#: hat (2xx-4xx) alan kodu, ardından 7 hane, gevşek şekilde
#: boşluk/nokta/tire ile gruplanmış. Ayırıcılar konusunda esnek bırakıldı
#: çünkü gerçek belgeler telefon numaralarını akla gelebilecek her şekilde
#: biçimlendiriyor; belirsizliği kalıp değil, güven skoru taşır.
_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+90[ ]?|0)?(5\d{2}|2\d{2}|3\d{2}|4\d{2})"
    r"[ .\-]?\d{3}[ .\-]?\d{2}[ .\-]?\d{2}(?!\d)"
)
#: Yakında bir telefon etiketi varlığı güveni artırır -- gerçek bir telefon
#: numarasını rastgele bir 10 haneli diziden (örn. daha uzun bir referansın
#: parçası) ayırır.
_PHONE_CONTEXT = re.compile(r"\b(tel|telefon|gsm|cep)\b", re.IGNORECASE)

#: Adres sezgisi: bir içerik satırı, sokak düzeyinde bir anahtar kelime
#: taşıdığında (mahalle/cadde/sokak/...) adres olarak puanlanır -- bu,
#: yalnızca gerçek bir adreste görülen kısımdır. Aşağıdaki birim düzeyi
#: anahtar kelimelerden bilerek ayrıldı: "Kat: 2" gibi sıradan bir resmi
#: yazı satırı veya "No: 5" gibi numaralı bir referans (bir dosya/belge
#: numarası, bir madde numarası, bir liste öğesi) tam olarak aynı kelimeleri
#: bir adres olmadan da kullanır ve eskiden tek başına bir adres olarak
#: yanlış pozitif üretmeye yetiyordu (bkz. Görev'in "hatalı PII tespiti" bug
#: raporu). Gerçek bir adresin bir sokak da adlandırması beklenir, bu yüzden
#: birim düzeyi anahtar kelimeler sayılmadan önce en az bir sokak düzeyi
#: eşleşme şart koşmak bu boşluğu kapatır.
_ADDRESS_STREET_KEYWORDS = re.compile(
    r"\b(mahalle(si)?|mah\.|cadde(si)?|cad\.|sokak|sok\.|bulvar[ıi]?|"
    r"apartman[ıi]?|blok)\b",
    re.IGNORECASE,
)

#: Birim düzeyi anahtar kelimeler: yalnızca bir sokak düzeyi eşleşme bu
#: satırın gerçekten bir adresle ilgili olduğunu zaten doğruladığında
#: anlamlıdır (yukarıya bakın) -- tek başlarına bunlar (kat/daire/no hepsi
#: herhangi bir adresle ilgisiz resmi yazışmalarda sürekli görünür) kendi
#: başlarına herhangi bir sinyal taşımak için çok fazla geneldir.
_ADDRESS_UNIT_KEYWORDS = re.compile(
    r"\b(kat\s*:?\s*\d|daire\s*:?\s*\d|no\s*:?\s*\d+)\b",
    re.IGNORECASE,
)

#: Bu sayının altındaki birleşik anahtar kelime eşleşmelerinde bir satır
#: güvenle bir adres sayılmaz.
_ADDRESS_MIN_KEYWORD_HITS = 2


class PiiFinding(BaseModel):
    """Yalnızca değerin maskelenmiş bir önizlemesini taşıyan tek bir PII kalıp eşleşmesi.

    ``confidence``, çağıranların gerçek bir bulguyu kalıp gürültüsünden
    ayırmak için ``GuardrailPolicy.pii_confidence_floor``'u uygulamasına
    izin verir (bkz. ``app.ai.guardrails.sensitivity.assess``) -- kendisi
    asla hassas değildir, bu yüzden bulgunun yanında loglanması veya
    kalıcı hale getirilmesi güvenlidir. Zorunlu olmak yerine 1.0 varsayılan
    değeri taşır: zaten filtrelenmiş, zaten serileştirilmiş bir
    değerlendirmeden yeniden oluşturulmuş bir bulgunun (bkz.
    ``app.ai.guardrails.sensitivity.assessment_from_analysis``, ki bu
    başından beri hiç confidence alanı taşımayan API'ye dönük
    ``GuardrailAssessmentSchema.pii_findings`` şeklini geri okur) raporlayacak
    orijinal bir güven skoru yoktur ve birini uydurmasına gerek olmamalıdır.
    """

    kind: str = Field(description="'tckn' | 'iban' | 'telefon' | 'adres'.")
    preview: str = Field(description="Maskelenmiş önizleme; ham değer taşımaz.")
    confidence: float = Field(default=1.0, description="0-1 arası güven skoru.")
    #: Hangi detektörün/kuralın gerçekten tetiklendiği -- "hangi detector
    #: nedeniyle tetiklendi" sorusunun cevabı (Görev'in kendi
    #: açıklanabilirlik gereksinimi). Aynı `confidence`'ın kendi
    #: docstring'inde açıkladığı nedenle zorunlu olmak yerine "" varsayılan
    #: değerini taşır: zaten serileştirilmiş bir değerlendirmeden yeniden
    #: oluşturulmuş bir bulgu bunu da hiç taşımamıştır.
    rule_id: str = Field(
        default="",
        description=(
            "Tetiklenen kural: 'tckn_checksum' | 'iban_mod97' | "
            "'phone_labeled' | 'phone_unlabeled' | 'address_street'."
        ),
    )


def _mask(value: str, *, keep_start: int = 2, keep_end: int = 2) -> str:
    """Bir değerin ortasını kırp, her uçta yalnızca birkaç karakteri görünür bırak.

    Args:
        value: Ham eşleşen değer.
        keep_start: Başta görünür bırakılacak karakter sayısı.
        keep_end: Sonda görünür bırakılacak karakter sayısı.

    Returns:
        Maskelenmiş bir önizleme, örn. ``"12*******34"``.
    """
    stripped = value.strip()
    if len(stripped) <= keep_start + keep_end:
        return "*" * len(stripped)
    middle = "*" * (len(stripped) - keep_start - keep_end)
    # `stripped[-0:]`, "son sıfır karakter" değil, string'in tamamıdır --
    # Python'da `-0 == 0`, dolayısıyla saf bir `stripped[-keep_end:]`, bir
    # çağıran 0 sondaki karakteri tutmayı istediğinde (adres bulucunun
    # yaptığı gibi) değerin tamamını geri sızdırır. Sıfır durumunu açıkça
    # koru.
    tail = stripped[-keep_end:] if keep_end > 0 else ""
    return f"{stripped[:keep_start]}{middle}{tail}"


def _tckn_checksum_valid(digits: str) -> bool:
    """11 haneli bir string'i Türk TCKN checksum algoritmasına karşı doğrula.

    Args:
        digits: Tam olarak 11 ASCII rakam karakteri.

    Returns:
        Her iki kontrol hanesi de (10. ve 11. pozisyonlar) ilk dokuzla
        tutarlıysa ve numara 0 ile başlamıyorsa True.
    """
    if digits[0] == "0":
        return False
    nums = [int(char) for char in digits]
    odd_sum = nums[0] + nums[2] + nums[4] + nums[6] + nums[8]
    even_sum = nums[1] + nums[3] + nums[5] + nums[7]
    tenth = (odd_sum * 7 - even_sum) % 10
    if tenth != nums[9]:
        return False
    eleventh = sum(nums[:10]) % 10
    return eleventh == nums[10]


def _iban_checksum_valid(iban: str) -> bool:
    """Bir Türk IBAN'ını ISO 7064 MOD97-10 checksum'ına karşı doğrula.

    Args:
        iban: Boşlukları kaldırılmış, büyük harfe çevrilmiş IBAN.

    Returns:
        Checksum tutuyorsa ve uzunluk bir Türk IBAN'ıyla (26 karakter:
        "TR" + 24 hane) eşleşiyorsa True.
    """
    if len(iban) != 26 or not iban.startswith("TR"):
        return False
    rearranged = iban[4:] + iban[:4]
    try:
        # Tek bir karakterin base-36 değeri, harfler için tam olarak ISO
        # 7064'ün harf kuralıdır (A=10 ... Z=35), rakamlar için ise
        # rakamın kendi değeridir -- ayrı bir arama tablosuna gerek yok.
        numeric = "".join(str(int(char, 36)) for char in rearranged)
    except ValueError:
        return False
    return int(numeric) % 97 == 1


#: Bir eşleşme artı kaynak metinde nerede bulunduğu. Konumlar yalnızca
#: :func:`redact_pii`'yi mümkün kılmak için var (bir string arayıp
#: umut etmek yerine tam aralığı değiştirmek) -- :func:`find_pii` bunları
#: atar, çünkü bu modül dışındaki hiçbir şey, kendisi saklanmaması gereken
#: bir metne ham bir ofsete asla ihtiyaç duymamıştır.
_PositionedFinding = tuple[int, int, PiiFinding]


def _find_tckn_positioned(text: str) -> list[_PositionedFinding]:
    results: list[_PositionedFinding] = []
    for match in _TCKN_PATTERN.finditer(text):
        digits = match.group(0)
        if _tckn_checksum_valid(digits):
            results.append(
                (
                    match.start(),
                    match.end(),
                    PiiFinding(
                        kind="tckn", preview=_mask(digits), confidence=0.95, rule_id="tckn_checksum"
                    ),
                )
            )
    return results


def _find_iban_positioned(text: str) -> list[_PositionedFinding]:
    results: list[_PositionedFinding] = []
    for match in _IBAN_PATTERN.finditer(text):
        raw = match.group(0)
        normalized = raw.replace(" ", "").upper()
        if _iban_checksum_valid(normalized):
            results.append(
                (
                    match.start(),
                    match.end(),
                    PiiFinding(
                        kind="iban",
                        preview=_mask(raw, keep_start=4, keep_end=2),
                        confidence=0.95,
                        rule_id="iban_mod97",
                    ),
                )
            )
    return results


def _find_phone_positioned(text: str) -> list[_PositionedFinding]:
    results: list[_PositionedFinding] = []
    for match in _PHONE_PATTERN.finditer(text):
        start = max(0, match.start() - 20)
        nearby = text[start : match.start()]
        labeled = bool(_PHONE_CONTEXT.search(nearby))
        confidence = 0.85 if labeled else 0.55
        results.append(
            (
                match.start(),
                match.end(),
                PiiFinding(
                    kind="telefon",
                    preview=_mask(match.group(0)),
                    confidence=confidence,
                    rule_id="phone_labeled" if labeled else "phone_unlabeled",
                ),
            )
        )
    return results


def _find_address_positioned(text: str) -> list[_PositionedFinding]:
    results: list[_PositionedFinding] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped:
            street_hits = len(_ADDRESS_STREET_KEYWORDS.findall(stripped))
            unit_hits = len(_ADDRESS_UNIT_KEYWORDS.findall(stripped))
            hits = street_hits + unit_hits
            # Bir sokak düzeyi eşleşme zorunludur -- kat/daire/no'nun tek
            # başına (kaç kez tekrarlanırsa tekrarlansın) neden asla yeterli
            # olmaması gerektiği için _ADDRESS_UNIT_KEYWORDS'ün kendi
            # docstring'ine bakın.
            if street_hits >= 1 and hits >= _ADDRESS_MIN_KEYWORD_HITS:
                # `line.index(stripped)`, `.strip()`'in tam olarak ne kadar
                # baştaki boşluğu kaldırdığını geri kazanır, böylece
                # eşleştirme kırpılmış kopya üzerinde çalışmış olsa bile
                # aralık orijinal metinle hizalanır.
                local_start = line.index(stripped)
                start = offset + local_start
                end = start + len(stripped)
                confidence = min(0.5 + 0.1 * hits, 0.9)
                preview = _mask(stripped, keep_start=6, keep_end=0).rstrip("*") + "…"
                results.append(
                    (
                        start,
                        end,
                        PiiFinding(
                            kind="adres", preview=preview, confidence=confidence, rule_id="address_street"
                        ),
                    )
                )
        offset += len(line)
    return results


def _find_all_positioned(text: str) -> list[_PositionedFinding]:
    if not text:
        return []
    return [
        *_find_tckn_positioned(text),
        *_find_iban_positioned(text),
        *_find_phone_positioned(text),
        *_find_address_positioned(text),
    ]


def find_pii(text: str) -> list[PiiFinding]:
    """Metni Türkçe PII kalıpları için tara.

    Burada bilerek güvene göre filtrelenmemiştir -- çağıranlar (başlıca
    ``app.ai.guardrails.sensitivity.assess``) ``GuardrailPolicy.pii_confidence_floor``'u
    uygular, böylece eşik tarayıcının içine gömülmek yerine tek, ayarlanabilir
    bir yerde yaşar.

    Args:
        text: Taranacak ham metin (belge metni, veya çıktı tarafı sızıntı
            kontrolü için üretilmiş bir yanıt).

    Returns:
        Bulunan her kalıp eşleşmesi, her biri yalnızca maskelenmiş bir
        önizlemeyle.
    """
    return [finding for _start, _end, finding in _find_all_positioned(text)]


def redact_pii(text: str, *, confidence_floor: float = 0.0) -> tuple[str, list[PiiFinding]]:
    """``text``'teki her PII aralığını kendi maskelenmiş önizlemesiyle değiştir.

    ``app.ai.guardrails.output_gate`` tarafından, üretilmiş bir yanıtı
    tamamen engellemek yerine yerinde kırpmak için kullanılır: bir belge
    yüklemesinin aksine (ki ya PII'si vardır ya da yoktur), bir yanıtın PII
    aralıklarının yalnızca yanında raporlanması değil, kullanıcının gördüğü
    metinden gerçekten kaldırılması gerekir.

    Args:
        text: Kırpılacak metin.
        confidence_floor: Bu güvenin altındaki bulgular olduğu gibi
            bırakılır, başka yerlerdeki ``GuardrailPolicy.pii_confidence_floor``
            ile aynı eşik rolü.

    Returns:
        Kırpılmış metin (hiçbir şey eşiği aşmadıysa değişmeden), ve
        gerçekten kırpılan bulgular.
    """
    matches = [m for m in _find_all_positioned(text) if m[2].confidence >= confidence_floor]
    if not matches:
        return text, []

    # En yüksek başlangıç ofsetinden aşağıya doğru değiştir, böylece bir
    # aralığı değiştirmek (ki bu metnin uzunluğunu değiştirebilir), hepsi
    # string'de daha önce yer alan henüz işlenmemiş ofsetleri asla geçersiz
    # kılmaz.
    redacted = text
    for start, end, finding in sorted(matches, key=lambda m: m[0], reverse=True):
        redacted = redacted[:start] + finding.preview + redacted[end:]

    findings = [finding for _start, _end, finding in matches]
    return redacted, findings
