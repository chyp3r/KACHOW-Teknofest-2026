"""Bir mesajı kanıt kurallarına (evidence rules) göre puanlar ve marja göre karar verir.

Karar, en yüksek skor değil, en yüksek iki intent arasındaki *marjdır*.
Baseline'ın ölçtüğü hataları düzeltilebilir kılan tek seçim budur:

* Hem bir yazım (drafting) ifadesi hem de bir analiz ifadesi taşıyan bir
  mesaj, iki yakın skor üretir. Küçük bir marj, keyfi olarak çözülecek bir
  berabelik değildir -- bilgidir ve eski kademenin (cascade) o an ilk hangi
  kuralı kontrol ettiğine değil, bir bileşik plana veya bir yükseltmeye
  (escalation) yönlendirir.
* Bir alan (domain) ismi artı tanımlayıcı bir karşıt-sinyal ("Üst yazı ne
  demek?") taşıyan bir mesaj, draft'a *negatif* bir katkı ve assist'e
  pozitif bir katkı üretir; böylece her gerçek isteğin dayandığı yazım
  ifadelerini zayıflatmadan assist'e çözümlenir.

Buradaki her şey bir tablo üzerinde aritmetiktir -- model çağrısı yok,
milisaniyenin altında ve tekrarlanabilir. Önceki çözümleyici, örüntü
eşleştiremediği her mesajı yükseltirken, bu yalnızca kanıtın gerçekten
dengeli veya gerçekten yok olduğu yerlerde yükseltiyor; doğruluk artarken
yükseltme oranının düşmesinin nedeni de bu.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from app.ai.policy import get_policy
from app.ai.workflows.intent_rules import (
    ALL_RULES,
    CONTINUABLE_INTENTS,
    CONTINUATION_SURFACES,
    QUESTION_SURFACES,
    WEIGHT_COUNTER,
    WEIGHT_DOMAIN,
    WEIGHT_HINT,
    EvidenceRule,
    Intent,
)

logger = logging.getLogger(__name__)

_INTENT_POLICY = get_policy().intent

#: En üstteki intent'in kararlı sayılması için ikinci sıradakine karşı ihtiyaç duyduğu minimum fark.
DECISIVE_MARGIN = _INTENT_POLICY.decisive_margin

#: Bir intent'in gerçekten mevcut sayılması için minimum skor. Bunun
#: altında bir intent, bir aday değil gürültüdür -- bir taban değeri
#: olmadan, 0.1 ve 0.0 puanlayan iki kural, güvenli bir karar gibi
#: okunurdu.
PRESENCE_FLOOR = _INTENT_POLICY.presence_floor

#: Marj `DECISIVE_MARGIN`'in altındayken, bu değere eşit veya üstünde olan
#: her iki intent de yükseltilecek bir belirsizlik yerine bileşik bir
#: istek olarak ele alınır.
COMPOUND_FLOOR = _INTENT_POLICY.compound_floor

#: Bir marjı [0, 1] aralığında bir confidence'a dönüştürmek için kullanılan
#: skor. Bu kadar bir fark tam confidence olarak okunur; değer, temiz
#: tek-kural isabeti ile tartışmalı bir isabet arasında gözlemlenen
#: farktır.
CONFIDENCE_SCALE = _INTENT_POLICY.confidence_scale

_TURKISH_MAP = str.maketrans(
    {
        "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i",
        "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
    }
)


@dataclass
class IntentScores:
    """Tek bir mesaj için tam puanlama sonucu.

    Attributes:
        scores: Intent -> birikmiş ağırlık.
        evidence: Ateşlenen kural id'leri, kural-tablosu sırasında.
        ranked: Skora göre sıralanmış intent'ler.
    """

    scores: dict[str, float] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)

    @property
    def ranked(self) -> list[tuple[str, float]]:
        """En yüksekten başlayarak intent'ler; berabelikler kararlılık için isme göre çözülür."""
        return sorted(self.scores.items(), key=lambda item: (-item[1], item[0]))

    @property
    def margin(self) -> float:
        """En üstteki intent'in ikinci sıradakine göre farkı. İkiden azsa 0.0."""
        ranked = self.ranked
        if len(ranked) < 2:
            return ranked[0][1] if ranked else 0.0
        return ranked[0][1] - ranked[1][1]

    @property
    def confidence(self) -> float:
        """[0, 1] aralığına eşlenmiş marj."""
        return max(0.0, min(1.0, self.margin / CONFIDENCE_SCALE))


def normalize(text: str) -> str:
    """İfade eşleştirme için Türkçe metni küçük harfli ASCII'ye indirger.

    Args:
        text: Ham kullanıcı metni.

    Returns:
        Noktalama işaretleri tek boşluklara indirgenmiş küçük harfli ASCII.
    """
    folded = (text or "").translate(_TURKISH_MAP)
    folded = unicodedata.normalize("NFKD", folded)
    ascii_text = folded.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


def _compile_surface(surface: str) -> re.Pattern:
    """Bir kural surface'ini sol kelime sınırıyla, sağ sınır olmadan derler.

    Yalnızca sol sınır, Türkçe morfolojisine özenmeden somut yanlış pozitifi
    ("uzatma" içindeki "uzat") düzeltir: dil sondan eklemelidir, bu yüzden
    meşru bir isabet genellikle yalın surface'in ötesine devam eder
    ("kisalt" için "kısaltır mısın", ama yalnızca kural surface'inin
  kendisi ekin başladığı yerde bitiyorsa "revize et" için "revize edelim").
    Sağ taraf kasıtlı olarak açık bırakıldı.
    """
    return re.compile(r"(?<![a-z0-9])" + re.escape(surface))


#: Surface başına derlenmiş bir örüntü, kural id'sine göre anahtarlanmış ve
#: her çağrıda değil import zamanında bir kez inşa edilmiş -- `ALL_RULES`
#: sabit bir modül seviyesi tuple, dolayısıyla geçersiz kılınacak bir şey
#: yok.
_SURFACE_PATTERNS: dict[str, tuple[re.Pattern, ...]] = {
    rule.id: tuple(_compile_surface(surface) for surface in rule.surfaces)
    for rule in ALL_RULES
}


def _fires(
    rule: EvidenceRule, normalized: str, has_document: bool, has_active_draft: bool
) -> bool:
    """Bir kuralın bu mesaja uygulanıp uygulanmadığını bildirir."""
    if rule.requires_document is not None and rule.requires_document is not has_document:
        return False
    if (
        rule.requires_active_draft is not None
        and rule.requires_active_draft is not has_active_draft
    ):
        return False
    return any(pattern.search(normalized) for pattern in _SURFACE_PATTERNS[rule.id])


def looks_like_question(raw: str, normalized: str) -> bool:
    """Mesajın bir şey sorup sormadığına sezgisel (heuristic) olarak karar verir.

    Public (`_` ön eki yok): yalnızca `score_intents` içinde değil,
    `router_features.extract_features` tarafından da fusion katmanının
    yapısal sinyallerinden biri olarak yeniden kullanılıyor.
    """
    if "?" in raw:
        return True
    padded = f" {normalized} "
    return any(f" {marker.strip()} " in padded for marker in QUESTION_SURFACES)


def score_intents(
    message: str,
    document_id: Optional[str],
    previous_intent: Optional[str] = None,
    has_active_draft: bool = False,
) -> IntentScores:
    """Her intent için kanıtı biriktirir.

    Args:
        message: Kullanıcının mesajı.
        document_id: Varsa, eklenmiş bir dokümanın depolama yolu.
        previous_intent: Biliniyorsa, önceki tur için çözümlenen intent.
        has_active_draft: `SessionFocus.active_draft`'ın ayarlı olup
            olmadığı -- `document_id`'nin yalnızca-doküman kuralını
            kapılaması gibi (bkz. `EvidenceRule.requires_active_draft`)
            `revise`'in kurallarını kapılar.

    Returns:
        Birikmiş skorlar ve ateşlenen her kuralın id'leri.
    """
    normalized = normalize(message)
    has_document = document_id is not None
    result = IntentScores()

    if not normalized:
        result.scores["assist"] = 10.0
        result.evidence.append("assist.empty_message")
        return result

    definitional = False
    for rule in ALL_RULES:
        if not _fires(rule, normalized, has_document, has_active_draft):
            continue
        result.scores[rule.intent] = result.scores.get(rule.intent, 0.0) + rule.weight
        result.evidence.append(rule.id)
        if rule.id == "assist.definitional_question":
            definitional = True

    # Tanımlayıcı bir soru bir kavram *hakkındadır*, dolayısıyla draft/analyze'i
    # tetikleyen alan ismi, eylemi talep etmek yerine konuyu tarif ediyordur.
    # İsmin kendi ağırlığını düşürmek yerine burada çıkarma yapmak, her
    # gerçek isteği tam güçte tutar.
    if definitional:
        for intent in ("draft", "analyze"):
            if intent in result.scores:
                result.scores[intent] += WEIGHT_COUNTER
                result.evidence.append(f"{intent}.definitional_counter")

    words = normalized.split()

    # Kısa bir onaylama, önceki turun intent'ini devam ettirir. Uzunlukla
    # sınırlandırıldı, böylece "evet, ama önce şunu incele" bunun yerine
    # içeriğine göre puanlanır.
    #
    # Mesaj bir selamlama, nezaket ifadesi veya vedaysa bastırılır: bir
    # draft turundan sonra gelen "İyi akşamlar, yarın devam ederiz" "devam"
    # içerir ama bir vedadır ve bunu onay olarak okumak eski çözümleyicide
    # tam bir yazım (drafting) çalışması üretiyordu. Bir veda, "devam"ın
    # "şimdi devam et"in tam tersi anlama geldiği tek yerdir.
    #
    # Mesajın kendisi bir soruysa da bastırılır: bir draft turundan sonra
    # gelen "Peki sence bu yeterli mi" "peki" içerir (bir devam surface'i)
    # ama asistanın görüşünü soruyordur, bir sonraki eylemi onaylamıyordur --
    # bunu draft devamı olarak puanlamak, kullanıcının sohbet tarzı bir
    # cevap beklediği bir sorudan tüm ikinci bir yazım pipeline'ı
    # çalıştırıyordu.
    #
    # Bir REVISE_RULES kuralı zaten `previous_intent`'ten *farklı* bir
    # intent için ateşlenmişse de bastırılır: bir draft turundan sonra gelen
    # "Kapanışı 'Saygılarımızla arz ederiz.' yap." somut bir hedef adlandırır
    # ("kapanış") ve beş kelimedir, dolayısıyla hem `revise.explicit_request`'i
    # ateşler (mesaj düzenlenecek bir alan adlandırıyor -- bkz. REVISE_RULES'in
    # kendi docstring'i: aktif bir draft'a kapılanmış olduğundan, makul olarak
    # başka bir anlamı olamaz) *hem de* bu kuralın kendi yalın "yap"
    # surface'iyle eşleşir -- buradaki "yap" cümlenin gerçek fiilidir, yalın
    # bir "devam et" onayı değildir, ama yukarıdaki hiçbir şey farkı
    # anlayamazdı. Bastırılmadan bırakıldığında, devam bonusu `draft`'ın
    # üzerine WEIGHT_HINT * 3 yığıyordu ve mesajın kendi, daha spesifik olan
    # `revise` kanıtından daha yüksek puan alıyordu -- "sayıyı siliyor"a
    # yakın raporun gerçek router seviyesindeki nedeni buydu: hedeflenmiş bir
    # revize talimatı sessizce yeni bir draft olarak yeniden çalışıyordu.
    fired_intents = {evidence_id.split(".", 1)[0] for evidence_id in result.evidence}
    contested_by_other_intent = bool(fired_intents - {previous_intent})
    signing_off = {"assist.greeting", "assist.courtesy", "assist.farewell"}.intersection(
        result.evidence
    )
    if (
        previous_intent in CONTINUABLE_INTENTS
        and not signing_off
        and not contested_by_other_intent
        and len(words) <= 6
        and not looks_like_question(message, normalized)
        and any(f" {surface} " in f" {normalized} " for surface in CONTINUATION_SURFACES)
    ):
        result.scores[previous_intent] = (
            result.scores.get(previous_intent, 0.0) + WEIGHT_HINT * 3
        )
        result.evidence.append(f"{previous_intent}.continuation")

    # Eklenmiş bir dokümanla gelen bir soru `assist`'e meyleder -- bu bir
    # ipucudur, bir kapı değil. Eski çözümleyici bunu bir dal (branch) haline
    # getiriyordu, bu yüzden dokümanı eklenmiş "Sen neler yapabilirsin?" bir
    # doküman sorusu haline geliyordu.
    #
    # HINT yerine DOMAIN ile ağırlıklandırıldı, böylece tek başına presence
    # floor'unu geçebiliyor: "Evrakın konusu nedir?" başka hiçbir doküman
    # ifadesi taşımıyor ve aday olamayacak kadar zayıf bir ipucu, bu tür her
    # soruyu modele gönderirdi.
    #
    # `chat` ve `document_qa` tek bir `assist` kovasında birleşmeden önce, bu
    # kuralın document_qa için pozitif sinyalinin, mesajın aslında `chat`
    # olduğunu savunan aşağıdaki iki karşıt sinyale (bir hafıza-hatırlatma
    # sorusu, kibarca ifade edilmiş bir istek) karşı savunulması
    # gerekiyordu. Her iki okuma da artık aynı intent'e düşüyor, dolayısıyla
    # hakemlik edilecek bir şey kalmadı -- burada eskiden çalışan yumuşatıcı
    # (softener) ve hafıza-hatırlatma karşıtları yeniden adlandırılmadı,
    # kaldırıldı, çünkü tek amaçları bu birleşmenin ortadan kaldırdığı bir
    # gerilimi çözmekti.
    if has_document and looks_like_question(message, normalized):
        result.scores["assist"] = (
            result.scores.get("assist", 0.0) + WEIGHT_DOMAIN
        )
        result.evidence.append("assist.question_with_document")

    # Hiçbir şey eklenmemiş çok kısa bir mesaj sohbet dolgusudur (filler) --
    # bir devam mesajı olması dışında; o durumda kısalık, iki kez sayılan
    # *aynı* kanıttır. "evet, hazırla" tam olarak bir onaylama olduğu için
    # kısadır ve her iki sinyalin de ateşlenmesine izin vermek, anlamı şüphe
    # götürmeyen bir mesajı yükseltecek kadar iki skoru birbirine yakın
    # bırakıyordu.
    #
    # Bir draft açıkken de tutuluyor: başka hiçbir şey eklenmemişken kısa
    # bir mesaj normalde dolgudur, ama aktif bir draft'la, hedeflenmiş bir
    # revizyon talimatının aldığı en yaygın tek biçimdir ("giriş kısmını
    # yumuşat" dört kelimedir). Burada `assist`'i doldurmak, o kısalığın tek
    # başına `revise`'in kendi açık kurallarından daha yüksek puan almasına
    # izin veriyordu; `REVISE_RULES` zaten `requires_active_draft` üzerinden
    # kapılanıyor, dolayısıyla bir draft açıldığında bu ipucunun hakemlik
    # edecek bir şeyi kalmıyor.
    continued = f"{previous_intent}.continuation" in result.evidence
    if not has_document and not has_active_draft and not continued and len(words) <= 4:
        result.scores["assist"] = result.scores.get("assist", 0.0) + WEIGHT_HINT * 2
        result.evidence.append("assist.short_message")

    # Hiçbir revise fiili içermeyen, draft'ın muhatabını adlandıran bir
    # ifade ("Muhatap Ankara Valiliği olsun.") bugün hiçbir şey puanlamıyor
    # -- her REVISE_RULES surface'i açık bir fiildir ("değiştir", bir
    # ton/uzunluk ipucuyla birlikte "yap"), ve yalnızca "muhatap" bunlardan
    # hiçbirini adlandırmaz. Bu olmadan, tam olarak eksik-bilgi kapısının
    # kendi cevabını sağlayan mesaj ("bilgi kısmı hiçbir yere yazılmıyor" --
    # bkz. intent_rules.py'ın modül docstring'i) hiçbir şey için kanıt
    # taşımaz ve ortada bulunan zayıf her ne dolgu varsa ona düşer.
    # REVISE_RULES'in kendisiyle aynı şekilde kapılanmış (has_active_draft)
    # ve bir soru olduğunda hariç tutuluyor ("Muhatap kim?" değiştirme
    # isteği değil, mevcut değeri soruyor) -- her iki koşul da
    # sağlandığında, bir draft zaten revizyon için açıkken bu mesajın makul
    # olarak başka bir anlamı olamaz.
    if (
        has_active_draft
        and not looks_like_question(message, normalized)
        and " muhatap " in f" {normalized} "
    ):
        result.scores["revise"] = result.scores.get("revise", 0.0) + WEIGHT_DOMAIN
        result.evidence.append("revise.muhatap_statement")

    return result
