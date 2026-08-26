"""Bir taslak var olmadan önce, kimin kime yazdığının deterministik çözümü.

``app.ai.workflows.draft_graph._build_brief``, gelen belgenin
sınıflandırmasından ``Muhatap``/``Gönderen Kurum``'u üretir, ancak bu iki
adın *yazan* kişiye göre hangi yöne işaret ettiğini hiç belirtmez. Belgesiz
bir istek için sınıflandırma ikisini de hiç taşımaz. Her iki durumda da
writer prompt'unda, kullanıcının kendi metnindeki hangi özel adın gönderen,
hangisinin muhatap olduğunu söyleyen hiçbir şey yoktur -- bu yüzden gördüğü
tek adı ("KACMAK ekibi olarak") prompt'un tanımladığı tek slota, yani
``Muhatap``'a koyar; bu da isteği yapan ekibe *gönderilen* değil, o ekip
*tarafından yazılan* bir taslak üretilmesi gerekirken tam tersini üretir.

Bu modül bunun düzeltmesidir: küçük bir yazım stili slot kümesi (kim
yazıyor, kime gidiyor, birinci çoğul mu yoksa kurumsal ses mi, kapanış
formülü) kullanıcının mesajından ve belgenin kendi sınıflandırmasından
deterministik olarak çözülür, yalnızca çözülemediğinde sorulur ve asla bir
model tarafından değil -- nedeni için :func:`resolve_brief`'in kendi
docstring'ine bakın. ``app.ai.workflows.correspondence`` ile aynı iki
parçalı şekil: bir çözümleyici (``resolve_brief``) ve bir prompt
oluşturucu (``format_writing_brief``).

Her çözümleyici çağrısı ikiye değil üç katmandan birine düşer:

* **Emin (Confident)** -- güçlü, spesifik bir sinyal (açık bir "X ekibi
  olarak", belgenin kendi başlık alanı, ya da -- ``muhatap`` için -- gerçek
  bir yazım fiiliyle aynı nefeste söylenmiş tek bir adlandırılmış muhatap,
  örn. "Ahmet Yılmaz'a bir izin yazısı hazırla"; bkz. ``_resolve_muhatap``'ın
  kendi docstring'i). Hiçbir zaman sorulmaz.
* **Önerilen (Suggested)** -- daha zayıf bir sinyal (yalın büyük harfli bir
  ifade, çıkarılmış bir hiyerarşi tahmini, birden fazla adlandırılmış aday)
  göstermeye değer ama sessizce güvenilmeye değmez. Yine de sorulur, ama
  tahmin sorunun ilk seçeneği olarak "(Önerilen)" etiketiyle birlikte gelir
  ve sorunun kendisi açık bir onay olarak ifade edilir ("Önerilen muhatap:
  X. Bu doğru mu?") -- bir tıklama yeniden yazmak yerine onaylar.
* **Bilinmiyor (Unknown)** -- elde hiçbir şey yok. Düz sorulur, önceden
  kayırılan bir seçenek yok.

Sadece emin katman bir soruyu tamamen bastırır; bir öneri hiçbir zaman
:attr:`BriefResolution.resolved` ("Bilinenler" şeridi) için "çözülmüş"
sayılmaz, çünkü aslında hiçbir şeyden çözülmemiştir, sadece tahmin
edilmiştir -- orada bir tahmini göstermek onu bilinen bir gerçek gibi
yanlış tanıtır.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

from app.ai.identity.parties import CounterParty, PartyContext, SelfParty
from app.ai.workflows.correspondence import (
    CORRESPONDENCE_TYPE_LABELS,
    match_genre,
)
from app.ai.workflows.intent_scorer import normalize

#: "Sen karar ver" sentinel değeri. Asla boş bırakılmaz: boş bir string,
#: bir residual-questions kontrolünün çalıştığı her yerde "cevaplanmamış"
#: olarak okunur; bu da kullanıcının açıkça "önemli değil" dediği bir slotu
#: yeniden sormaya yol açar.
AUTO_ANSWER = "__auto__"

#: Brief-gate kartı bir turda bundan fazla soru asla sormaz, böylece sekiz
#: alanlık bir forma dönüşemez. Slotlar bu sınır uygulanmadan önce
#: ``BriefSlotSpec.priority``'ye göre sıralanır, böylece hangi dördünün
#: seçileceği dict sıralamasına bağlı değil deterministiktir.
MAX_BRIEF_QUESTIONS = 4

SlotSource = Literal[
    "user_text", "classification", "document_reply", "prior_brief", "default", "company_profile"
]


@dataclass(frozen=True)
class AnswerOption:
    value: str
    label: str
    description: str = ""


_AUTO_OPTION = AnswerOption(value=AUTO_ANSWER, label="Sen karar ver")


@dataclass(frozen=True)
class SlotResolution:
    value: str
    source: SlotSource
    label: str = ""
    #: False, düşük güvenli bir tahmini işaretler: slot yine de sorulur
    #: (bkz. modül docstring'inin üç katmanlı ayrımı), bu değer doğrudan
    #: uygulanmak yerine sorunun önerilen seçeneği olarak sunulur.
    confident: bool = True


@dataclass(frozen=True)
class BriefSlotSpec:
    """Brief'in ya çözdüğü ya da hakkında soru sorduğu tek bir yazım stili gerçeği."""

    key: str
    header: str
    question: str
    options: tuple[AnswerOption, ...] = ()
    multi_select: bool = False
    allow_free_text: bool = True
    required: bool = True
    #: Hem sabit bir ``MAX_BRIEF_QUESTIONS`` alt kümesi seçmek hem de
    #: çözülen brief'i tahmin edilebilir bir sırada göstermek için kullanılan
    #: sabit sıralama.
    priority: int = 0

    def to_prompt_question(self, suggestion: Optional[SlotResolution] = None) -> dict[str, Any]:
        """Bu slotu, varsa bir öneriyi de içine katarak bir PromptQuestion olarak oluştur.

        Değeri bu slotun kendi katalog seçeneklerinden biriyle eşleşen bir
        öneri (örn. ``kapanis``'in "arz_ederim"'i) o seçeneği tekrarlamak
        yerine öne çıkarır ve önerilen olarak işaretler. Katalogda eşleşmesi
        olmayan bir öneri (tahmin edilmiş bir ad/kurum -- her zaman
        ``yazan_taraf``/``muhatap``, sabit seçenekleri hiç olmayan tek
        slotlar) bunun yerine kendi sentetik seçeneği olarak başa eklenir ve
        sorunun kendisi, slotun genel ifadesi ("Yazı kime gönderilecek?")
        yerine açık bir evet/hayır onayı olarak yeniden yazılır ("Önerilen
        muhatap: Ahmet Yılmaz. Bu doğru mu?") -- önerilen seçeneğe tıklamak,
        açık bir soruyu körlemesine cevaplamak değil, belirli bir tahmini
        onaylamak gibi okunmalıdır.
        """
        options = list(self.options)
        question_text = self.question
        if suggestion is not None:
            matched_index = next(
                (index for index, option in enumerate(options) if option.value == suggestion.value),
                None,
            )
            if matched_index is not None:
                matched = options[matched_index]
                recommended = AnswerOption(
                    value=matched.value,
                    label=f"{matched.label} (Önerilen)",
                    description=matched.description,
                )
                options = [recommended, *options[:matched_index], *options[matched_index + 1 :]]
            else:
                recommended = AnswerOption(
                    value=suggestion.value,
                    label=f"{suggestion.label or suggestion.value} (Önerilen)",
                    description="Sistemin önerisi",
                )
                options = [recommended, *options]
                # Sadece katalogsuz slotlar için (bkz. bu metodun kendi
                # docstring'i) -- katalog sahibi bir slotun sorusu ("Kapanış
                # ifadesi ne olsun?") önerilen bir seçenek başa alındığında
                # zaten gayet iyi okunur; yalın bir ad/kurumun gerektirdiği
                # gibi onaylanması gereken tahmin edilmiş bir değer adlandırmaz.
                question_text = (
                    f"Önerilen {self.header.lower()}: "
                    f"{suggestion.label or suggestion.value}. Bu doğru mu?"
                )
        # Katalog seçeneği olmayan bir slot (yazan_taraf/muhatap) için bile
        # her zaman mevcut -- her slot "Sen karar ver" sunar.
        options = [*options, _AUTO_OPTION]

        return {
            "key": self.key,
            "question": question_text,
            "header": self.header,
            "help": "",
            "example": suggestion.value if suggestion is not None and not self.options else None,
            "options": [
                {"value": option.value, "label": option.label, "description": option.description}
                for option in options
            ],
            "multi_select": self.multi_select,
            "allow_free_text": self.allow_free_text,
            "required": self.required,
        }


#: Bir taraf çözümlemeyen çağrı noktasının (bir test, veya bu modülün taraf
#: farkındalığından önce yazılmış bir çağıran) varsayılan olarak aldığı taraf
#: bağlamı -- her iki tarafta da `is_known=False`/`relation="none"`, böylece
#: her çözümleyicinin taraf-farkında dalı bir no-op olur ve davranış,
#: `PartyContext` var olmadan önce olduğu gibi tamamen metinsel sezgilere
#: geri düşer.
_UNKNOWN_PARTY = PartyContext(us=SelfParty(), them=CounterParty(), relation="none")


@dataclass(frozen=True)
class BriefEvidence:
    raw_text: str
    normalized_text: str
    fields: dict[str, Any]
    prior_brief: dict[str, Any]
    #: Bu mektubu kimin yazdığı ve gelen belgenin (varsa) gerçekten kimi
    #: adlandırdığı -- bkz. ``app.ai.identity.parties``. Bilinmeyen/nötr bir
    #: bağlama varsayılan olur (her çözümleyicinin taraf-farkında dalı bir
    #: no-op olur), böylece hiç çözümlemeyen bir çağıran -- bir test, veya
    #: taraf-modeli öncesi herhangi bir kod yolu -- bu alan var olmadan önce
    #: davrandığı gibi davranır.
    party: PartyContext = field(default_factory=lambda: _UNKNOWN_PARTY)


@dataclass(frozen=True)
class BriefResolution:
    #: Slot anahtarına göre gruplanmış, emin bir şekilde çözülmüş slotlar --
    #: "Bilinenler" şeridinin gösterdiği şey. Bir öneri asla buraya düşmez
    #: (bkz. modül docstring'i): hiçbir şeyden çözülmemiştir, sadece tahmin
    #: edilmiştir, bu yüzden burada göstermek onu bilinen bir gerçek gibi
    #: yanlış tanıtır.
    resolved: dict[str, SlotResolution] = field(default_factory=dict)
    #: Çözülmemiş slotlar için PromptQuestion şeklinde dict'ler; öncelik
    #: sırasına göre ve MAX_BRIEF_QUESTIONS ile sınırlı. Düşük güvenli bir
    #: tahmini olan bir slot yine de burada görünür, tahmin önerilen bir
    #: seçenek olarak içine katılmış halde.
    questions: tuple[dict[str, Any], ...] = ()


SLOT_CATALOG: tuple[BriefSlotSpec, ...] = (
    #: Öncelik 0 (en düşük sayı, önce sorulur / MAX_BRIEF_QUESTIONS
    #: sınırı tarafından asla dışarı itilmez) -- yazışma türünü yanlış
    #: bilmek tüm taslağı şekillendirir; bir revize turunun ucuza
    #: düzeltebileceği yanlış bir anlatım/kapanış tahmininin aksine. Bkz.
    #: app.ai.workflows.correspondence.resolve_correspondence_type: bu
    #: slotun çözülen cevabı, oradaki "açık" öncelik ifadesinin atıfta
    #: bulunduğu şeydir.
    BriefSlotSpec(
        key="yazisma_turu",
        header="Yazışma türü",
        question="Nasıl bir yazışma türü hazırlayayım?",
        options=tuple(
            AnswerOption(value=value.value, label=label)
            for value, label in CORRESPONDENCE_TYPE_LABELS.items()
        ),
        priority=0,
    ),
    BriefSlotSpec(
        key="yazan_taraf",
        header="Yazan taraf",
        question="Bu yazıyı kim yazıyor (göndereni)?",
        priority=1,
    ),
    BriefSlotSpec(
        key="muhatap",
        header="Muhatap",
        question="Yazı kime gönderilecek?",
        priority=2,
    ),
    BriefSlotSpec(
        key="anlatim",
        header="Anlatım",
        question="Hangi anlatım biçimini kullanayım?",
        options=(
            AnswerOption("birinci_cogul", "Biz dili", "Ekibimiz/kurumumuz olarak talep ediyoruz"),
            AnswerOption("kurumsal", "Kurumsal dil", "Kurum adına resmî üslup"),
            AnswerOption("birinci_tekil", "Ben dili", "Bireysel dilekçe"),
        ),
        priority=3,
    ),
    BriefSlotSpec(
        key="kapanis",
        header="Kapanış",
        question="Kapanış ifadesi ne olsun?",
        options=(
            AnswerOption("arz_ederim", "Arz ederim", "Üst makama"),
            AnswerOption("rica_ederim", "Rica ederim", "Alt/denk makama"),
            AnswerOption("arz_ve_rica_ederim", "Arz ve rica ederim", ""),
            AnswerOption("bilgilerinize_sunulur", "Bilgilerinize sunulur", "Eşit düzey/bilgi amaçlı"),
        ),
        priority=4,
    ),
    BriefSlotSpec(
        key="imza",
        header="İmza bloğu",
        question="İmza bloğunda ad/unvan yer tutucu mu kalsın?",
        options=(AnswerOption("yer_tutucu", "Yer tutucu bırak", "[Ad Soyad] / [Unvan]"),),
        required=False,
        priority=5,
    ),
    BriefSlotSpec(
        key="sayi",
        header="Sayı",
        # Tarih bilerek bu slotun bir parçası değildir -- hakkında hiçbir
        # zaman soru sorulmaz (bkz. app.ai.workflows.dates.today_tr ve
        # draft_graph._build_brief'in writer'ın kendi "Tarih:" satırını
        # otomatik dolduran "0. BUGÜNÜN TARİHİ" bölümü).
        question="Sayı alanı nasıl işlensin?",
        options=(
            AnswerOption("yer_tutucu", "Yer tutucu bırak", ""),
            AnswerOption("bos_birak", "Boş bırak", ""),
        ),
        required=False,
        priority=6,
    ),
)

_SLOT_BY_KEY: dict[str, BriefSlotSpec] = {spec.key: spec for spec in SLOT_CATALOG}


def _coerce_fields(classification: dict[str, Any]) -> dict[str, Any]:
    """Çıkarılan başlık alanlarını düz bir dict olarak döndür.

    Bilerek ``draft_graph``/``revise_graph``/``revision.retrieval``'dan
    kopyalanmıştır -- paylaşılan dört satırlık bir yardımcı burada
    modüller-arası bir bağımlılığa değmez.
    """
    fields = (classification or {}).get("fields", {})
    if hasattr(fields, "model_dump"):
        return fields.model_dump()
    return fields if isinstance(fields, dict) else {}


#: "<isim> <ek> olarak" ifadesinin muhatabın bir tanımı değil, yazanın kendi
#: beyanı olarak okunmasını sağlayan topluluk-ismi ekleri.
_COLLECTIVE_SUFFIX = (
    r"(?:ekibi|ekip|tak[ıi]m[ıi]|tak[ıi]m|kul[uü]b[uü]|kulup|derne[gğ]i|dernek|"
    r"toplulu[gğ]u|topluluk|firmasi|firma|sirketi|sirket|b[oö]l[uü]m[uü]|"
    r"b[oö]l[uü]m|birimi|birim)"
)

#: Aday bir ad token'ı: büyük harfle başlamalı (Latin veya Türkçe), böylece
#: topluluk isminden önceki sıradan küçük harfli Türkçe fiil/bağlaç dizisi
#: ("...dilekçe yazmak istiyoruz KACMAK ekibi olarak") hiçbir zaman
#: yakalanan ada karışamaz -- sadece gerçek özel isim yakalanabilir, çünkü
#: Türkçe cümle metni özel isimler ve cümle başları dışında küçük harflidir.
#: En fazla 4 token ile sınırlıdır, böylece gerçekten çok kelimeli bir ad
#: ("Hacettepe Bilişim Kulübü") yine bütün olarak eşleşir.
_NAME_TOKEN = r"[A-ZÇĞİÖŞÜ]\w*"

#: Emin: bir topluluk ismi ("... ekibi olarak") veya açık bir "adına" --
#: ikisi de göndereni belirsizlik olmadan adlandırır.
_YAZAN_TARAF_STRONG_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(
        rf"((?:{_NAME_TOKEN}\s+){{0,3}}{_NAME_TOKEN}\s+(?i:{_COLLECTIVE_SUFFIX}))\s+(?i:olarak)\b"
    ),
    re.compile(rf"((?:{_NAME_TOKEN}\s+){{0,3}}{_NAME_TOKEN})\s+(?i:ad[ıi]na)\b"),
)

#: Sadece önerilen: doğrudan "olarak" ile takip edilen, yukarıdaki topluluk
#: ismi şartı olmadan herhangi bir büyük harfli ifade -- güçlü desenin
#: yakalamadığı kişisel bir adı ("Ahmet Yılmaz olarak") yakalar, ama
#: kesinlikle yanlış tahmin etmek yerine bir tahmine değecek kadar gevşektir
#: (herhangi bir cümle-başı büyük harf + "olarak").
_YAZAN_TARAF_WEAK_PATTERN = re.compile(
    rf"((?:{_NAME_TOKEN}\s+){{0,3}}{_NAME_TOKEN})\s+(?i:olarak)\b"
)

#: Bir muhatabı emin bir şekilde tahmin etmek için derlenmiş kurum
#: kelime dağarcığı. Bilerek muhafazakâr -- bkz. modül docstring'i:
#: hiçbir eşleşme aşağıdaki zayıf desene düşmez, kesinlikle yanlış tahmin
#: etmek yerine.
_INSTITUTION_VOCABULARY: dict[str, str] = {
    "rektorluk": "Rektörlük",
    "dekanlik": "Dekanlık",
    "valilik": "Valilik",
    "kaymakamlik": "Kaymakamlık",
    "mudurluk": "Müdürlük",
    "bakanlik": "Bakanlık",
    "baskanlik": "Başkanlık",
    "komisyon": "Komisyon",
    "komite": "Komite",
    "genel sekreterlik": "Genel Sekreterlik",
    "teknofest": "TEKNOFEST",
    "tubitak": "TÜBİTAK",
}

#: Türkçe -e hali (dative) ekiyle, kesme işaretiyle işaretlenmiş büyük
#: harfli bir özel isim ("TEKNOFEST'e", "KACMAK'a", "Ahmet Yılmaz'a") --
#: bir hal eki alan özel isim için yazım kuralı, ve mektubun kime hitap
#: ettiğine dair makul bir sinyal.
_MUHATAP_DATIVE_APOSTROPHE_PATTERN = re.compile(
    rf"((?:{_NAME_TOKEN}\s+){{0,2}}{_NAME_TOKEN})'(?:e|a|ye|ya|ne|na)\b"
)

#: Aynı hal, kesme işareti olmadan -- çoğu insanın gerçekte yazdığı şekilde
#: bir ad/kurum ("Ahmet Yılmaza", "İnsan Kaynakları Müdürlüğüne"), yazım
#: kurallarına göre "doğru" kesme işaretli biçim değil. En uzun ek önce
#: gelir, böylece "-ne"/"-ya" kendi sondaki "-e"/"-a"'sı tarafından
#: gölgelenmez.
#:
#: Bilerek bir tampon-ünsüz analizinin önereceği üç harfli "üne"/"ına"/
#: "ine"/"una" biçimlerini de eşleştirmek yerine iki harfli tampon+hal
#: biçimlerinde ("ne"/"na"/"ye"/"ya") durur: bir Türkçe kurum adı, -e hali
#: eklenmeden önce ezici çoğunlukla zaten kendi iyelik ünlüsüyle biter
#: ("Müdürlüğü" + "ne" -> "Müdürlüğüne", "Fakültesi" + "ne" ->
#: "Fakültesine") -- eşleşen iki harfli eki çıkarmak bu (bu alanda baskın)
#: durumda tam kökü geri kazandırır. Bunun yerine üç harfli bir eki
#: çıkarmak, o kök ünlüsünü de yiyip bitirirdi ("Müdürlüğüne" ->
#: "Müdürlüğ", bir kelime değil). Ödünleşim şu: eklenen bir tampon ünlüden
#: önce yalın bir ünsüzle biten bir kök (örn. "ev" + "ine" -> "evine") bir
#: harf fazla uzun geri döner ("evi", "ev" değil) -- öneri katmanı bir
#: sezgi için kabul edilebilir bir kaçırma, ve bu alanda bir kişi/kurum
#: adının aldığı şekil değil.
_DATIVE_SUFFIXES: tuple[str, ...] = ("ya", "ye", "na", "ne", "a", "e")
_MUHATAP_DATIVE_BARE_PATTERN = re.compile(
    rf"((?:{_NAME_TOKEN}\s+){{0,2}}{_NAME_TOKEN}(?:{'|'.join(_DATIVE_SUFFIXES)}))\b"
)

#: "Sayın X" -- muhatabı açıkça adlandıran bir hitap, gerçek bir resmi
#: mektubun kendi muhatap satırının kullandığı aynı kural.
_MUHATAP_SAYIN_PATTERN = re.compile(
    rf"\bSay[ıi]n\s+((?:{_NAME_TOKEN}\s+){{0,3}}{_NAME_TOKEN})"
)

#: "X Bey'e" / "X Hanım'a" -- ad artı Türkçe unvan artı -e hali. Unvanı da
#: yakalar (görüntülenen değerde bilerek tutulur, örn. "Ahmet Bey" --
#: bunu bırakmak, kullanıcının bilerek seçtiği saygılı bir hitabı sessizce
#: düşürür).
_MUHATAP_HONORIFIC_PATTERN = re.compile(
    rf"((?:{_NAME_TOKEN}\s+){{0,2}}{_NAME_TOKEN}\s+(?:Bey|Hanım))'(?:e|ne)\b"
)

#: "X için" -- bir yazışmanın kimi ilgilendirdiğini hiçbir hal eki olmadan
#: adlandırmanın yaygın bir yolu.
_MUHATAP_ICIN_PATTERN = re.compile(
    rf"((?:{_NAME_TOKEN}\s+){{0,3}}{_NAME_TOKEN})\s+i[cç]in\b"
)

#: Bir aday değerin başındaki "Sayın "ı temizler -- "Sayın" kendisi büyük
#: harfli bir token'dır ve `_NAME_TOKEN`'ı sağlar, bu yüzden onu hariç
#: tutmak için hiçbir nedeni olmayan bir desen (özellikle
#: `_MUHATAP_ICIN_PATTERN`: "Sayın Ahmet Yılmaz için" "için" ile biten tek
#: uzun bir ad-token dizisi olarak okunur) aksi halde "Sayın Ahmet
#: Yılmaz"ı `_MUHATAP_SAYIN_PATTERN`'ın kendi "Ahmet Yılmaz"ından *farklı*
#: bir aday string olarak yakalardı -- açıkça aynı kişi için iki farklı
#: görünen aday, bu da tek adlı bir sözü yanlışlıkla "belirsiz"e düşürürdü.
_LEADING_SAYIN_PATTERN = re.compile(r"^Say[ıi]n\s+", re.IGNORECASE)

#: Bir taslak-isteği fiil kökü -- tek bir muhatap adayını emin olarak
#: doğrular (bkz. `_resolve_muhatap`): "Ahmet Yılmaz'a bir izin yazısı
#: hazırla" muhatabını "kime gönderilecek?" diye geri sormanın gereksiz
#: olacağı kadar belirsizlik olmadan adlandırır, tıpkı açık bir "X ekibi
#: olarak"ın yazan_taraf hakkında sormayı zaten atlaması gibi.
_WRITING_VERB_PATTERN = re.compile(r"\b(yaz|hazirla|olustur)\w*\b")

#: Yazışma hiyerarşisinde genellikle göndericinin üstünde olan kurum
#: anahtar kelimeleri -- çözülen/önerilen `muhatap` bunlardan birini
#: adlandırdığında ve ne "arz" ne de "rica" açıkça söylenmediğinde
#: `kapanis` için zayıf bir "Arz ederim" tahminini destekler.
_AUTHORITY_KEYWORDS = (
    "rektorluk", "dekanlik", "valilik", "kaymakamlik", "bakanlik",
    "baskanlik", "genel mudurluk",
)


def _resolve_yazisma_turu(
    evidence: BriefEvidence, known: dict[str, SlotResolution]
) -> Optional[SlotResolution]:
    del known
    match = match_genre(evidence.raw_text)
    if match is None:
        return None
    correspondence_type, sub_genre = match
    label = sub_genre or CORRESPONDENCE_TYPE_LABELS[correspondence_type]
    return SlotResolution(value=correspondence_type.value, source="user_text", label=label)


def _resolve_yazan_taraf(
    evidence: BriefEvidence, known: dict[str, SlotResolution]
) -> Optional[SlotResolution]:
    del known
    for pattern in _YAZAN_TARAF_STRONG_PATTERNS:
        match = pattern.search(evidence.raw_text)
        if match:
            value = match.group(1).strip(" ,.-")
            if value:
                return SlotResolution(value=value, source="user_text", label=value)

    # Yapılandırılmış bir şirket kimliği, bu mektubu kimin yazdığına dair
    # pipeline'da var olan en güvenilir sinyaldir -- *gelen* belgenin kendi
    # başlığından çıkarılan bir tahminden daha güvenilir; PartyContext var
    # olmadan önce bu buna geri düşüyordu (üretilen somut hata için bkz.
    # app.ai.identity.parties'in modül docstring'i: bir belgenin kendi
    # muhatabı, belgenin gerçekten bize hitap edip etmediği kontrol
    # edilmeden koşulsuzca bizim göndericimiz olarak ele alınıyordu).
    # Aşağıdaki document-reply yedeğinin üstüne bilerek yerleştirilmiştir:
    # o çıkarım da mevcut olsa bile, yönetici tarafından girilmiş bir
    # kimlik belge metninden bir çıkarıma kazanmalıdır.
    us = evidence.party.us
    if us.is_known:
        value = us.display_name or us.short_name
        if value:
            return SlotResolution(value=value, source="company_profile", label=value)

    # Gelen belgenin kendi muhatabını bizim gönderici slotumuza yalnızca
    # belge gerçekten bize hitap ediyor olarak doğrulandığında ters çevir
    # (bkz. resolve_party_context) -- asla koşulsuzca değil. Muhatabı bizim
    # yapılandırılmış kimliğimizle eşleşmeyen bir belge (bir özgeçmiş,
    # üçüncü taraf bir rapor, veya sadece doğrulayamadığımız biri) muhatabını
    # asla bizim kendi antet/imzamıza bağışlamamalıdır.
    if evidence.party.relation == "reply_to_us":
        document_muhatap = evidence.fields.get("muhatap")
        if document_muhatap:
            value = str(document_muhatap).strip()
            return SlotResolution(value=value, source="document_reply", label=value)

    weak_match = _YAZAN_TARAF_WEAK_PATTERN.search(evidence.raw_text)
    if weak_match:
        value = weak_match.group(1).strip(" ,.-")
        if value:
            return SlotResolution(value=value, source="user_text", label=value, confident=False)
    return None


def _strip_dative_suffix(phrase: str) -> str:
    """Eşleşen bir ifadenin son token'ından tanınan bir -e hali ekini çıkar.

    Sadece ``_MUHATAP_DATIVE_BARE_PATTERN`` buna ihtiyaç duyar -- diğer her
    muhatap deseni adı zaten hal eki olmadan yakalar (kesme
    işareti/unvan desenleri onu yapı gereği yakalama grubundan hariç
    tutar, ve "Sayın X"/"X için" hiç hal eki taşımaz).

    Args:
        phrase: Eşleşen tam ifade, örn. "Ahmet Yılmaza" veya
            "İnsan Kaynakları Müdürlüğüne".

    Returns:
        Son token'ının eki çıkarılmış ifade, örn. "Ahmet Yılmaz" /
        "İnsan Kaynakları Müdürlüğü". Listelenen hiçbir ek gerçekten
        eşleşmiyorsa girdiyi değişmeden geri döndürür (savunmacı; ``phrase``'i
        üreten desen zaten birinin eşleştiğini garanti eder).
    """
    words = phrase.rsplit(" ", 1)
    last = words[-1]
    for suffix in _DATIVE_SUFFIXES:
        if last.lower().endswith(suffix) and len(last) > len(suffix) + 1:
            words[-1] = last[: -len(suffix)]
            return " ".join(words)
    return phrase


def _muhatap_candidates(evidence: BriefEvidence) -> list[str]:
    """Kullanıcının kendi metninin adlandırdığı her olası muhatap ifadesi.

    Sıra yalnızca birden fazla aday olduğunda hangisinin öneri olarak
    sunulacağı için önemlidir (ilk bulunan); *sayı* ise ``_resolve_muhatap``'ta
    güveni belirleyen şeydir -- bir taslak fiiliyle doğrulanan tek bir aday
    emindir, geri kalan her şey (sıfır aday hariç) onaylanması gereken bir
    öneridir.

    Args:
        evidence: Bu turun çözülmüş girdisi.

    Returns:
        Farklı aday ifadeler (katlanmış biçime göre tekilleştirilmiş),
        desenlerin denendiği sırayla.
    """
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        value = _LEADING_SAYIN_PATTERN.sub("", raw.strip(" ,.-")).strip()
        if not value:
            return
        folded = normalize(value)
        if folded in seen:
            return
        seen.add(folded)
        candidates.append(value)

    for match in _MUHATAP_SAYIN_PATTERN.finditer(evidence.raw_text):
        _add(match.group(1))
    for match in _MUHATAP_HONORIFIC_PATTERN.finditer(evidence.raw_text):
        _add(match.group(1))
    for match in _MUHATAP_DATIVE_APOSTROPHE_PATTERN.finditer(evidence.raw_text):
        _add(match.group(1))
    for match in _MUHATAP_DATIVE_BARE_PATTERN.finditer(evidence.raw_text):
        phrase = match.group(1)
        # Mesajın en başındaki *tek* büyük harfli bir kelime güvenilir bir
        # ad sinyali değildir -- onu belirsizlikten kurtaracak bir kesme
        # işareti, unvan veya "Sayın" olmadan, tesadüfen -e hali biçimli bir
        # ekle biten sıradan bir cümle açılışı ("Yarışmaya katılmak
        # için...") aksi halde gerçek bir yalın -e hali adı gibi okunur
        # (bkz. `test_a_dative_marked_proper_noun_suggests_the_addressee`'in
        # kesme işaretli biçim için aynı keskin kenar üzerine kendi notu).
        # Aynı konumdaki *çok* kelimeli büyük harfli bir dizi ("Ahmet
        # Yılmaza bir izin yazısı hazırla", "İnsan Kaynakları
        # Müdürlüğüne...") bu riski taşımaz -- iki veya üç sıradan
        # kelimenin sebepsiz yere art arda büyük harfli olması, konumdan
        # bağımsız olarak, Türkçe cümlelerin yapmadığı bir şeydir -- bu
        # yüzden burada sadece tek-token durumu hariç tutulur.
        is_sentence_initial = not evidence.raw_text[: match.start()].strip()
        if is_sentence_initial and len(phrase.split()) == 1:
            continue
        _add(_strip_dative_suffix(phrase))
    for match in _MUHATAP_ICIN_PATTERN.finditer(evidence.raw_text):
        _add(match.group(1))

    return candidates


def _resolve_muhatap(
    evidence: BriefEvidence, known: dict[str, SlotResolution]
) -> Optional[SlotResolution]:
    del known
    # _resolve_yazan_taraf'ın kendi document-reply dalıyla aynı koruma:
    # belgenin kendi göndericisini bizim muhatap slotumuza sadece belge
    # bize hitap ediyor olarak doğrulandığında ters çevir. Aksi halde bu
    # kurum karşı tarafa aittir ve asla BİZİM kime yazdığımız olmamalıdır.
    if evidence.party.relation == "reply_to_us":
        document_sender = evidence.fields.get("gonderen_kurum")
        if document_sender:
            value = str(document_sender).strip()
            return SlotResolution(value=value, source="document_reply", label=value)
    for surface, label in _INSTITUTION_VOCABULARY.items():
        if re.search(rf"\b{re.escape(surface)}\w*\b", evidence.normalized_text):
            # Kullanıcının kendi mesajında geçen bizim kendi birimimiz
            # ("İnsan Kaynakları Müdürlüğü" *bizim* departmanlarımızdan
            # biri olarak), kimin yazdığını tanımlar, mektubun kime hitap
            # ettiğini asla tanımlamaz.
            if evidence.party.belongs_to_us(label):
                continue
            return SlotResolution(value=label, source="user_text", label=label)

    candidates = [
        candidate for candidate in _muhatap_candidates(evidence)
        if not evidence.party.belongs_to_us(candidate)
    ]
    if not candidates:
        return None

    value = candidates[0]
    # Gerçek bir taslak isteğiyle aynı nefeste söylenmiş tek bir
    # adlandırılmış aday ("Ahmet Yılmaz'a bir izin yazısı hazırla"), soruyu
    # tamamen atlamaya yetecek kadar belirsizlik içermez -- bkz.
    # _WRITING_VERB_PATTERN'ın kendi docstring'i. Birden fazla aday (mesaj
    # iki kişi/kurum adlandırıyor) veya hiç taslak fiili olmaması (geçici
    # bir söz, açıkça bir istek değil) bir öneri olarak kalır.
    if len(candidates) == 1 and _WRITING_VERB_PATTERN.search(evidence.normalized_text):
        return SlotResolution(value=value, source="user_text", label=value)
    return SlotResolution(value=value, source="user_text", label=value, confident=False)


def _resolve_anlatim(
    evidence: BriefEvidence, known: dict[str, SlotResolution]
) -> Optional[SlotResolution]:
    if any(pattern.search(evidence.raw_text) for pattern in _YAZAN_TARAF_STRONG_PATTERNS):
        return SlotResolution(value="birinci_cogul", source="user_text", label="Biz dili")
    yazan_taraf = known.get("yazan_taraf")
    if yazan_taraf is not None and yazan_taraf.source == "company_profile":
        # Şirketin kendisi gönderici olarak çözülmüştür (bkz.
        # _resolve_yazan_taraf) -- açık bir "... ekibi olarak"ın aldığı
        # aynı birinci çoğul ses, çünkü kendi adına yazan bir şirket tam
        # olarak aynı durumdur, sadece mesajın kendi ifadesi yerine
        # yapılandırılmış kimliğinden çözülmüştür.
        return SlotResolution(value="birinci_cogul", source="company_profile", label="Biz dili")
    if "dilekce" in evidence.normalized_text and not evidence.fields.get("gonderen_kurum"):
        return SlotResolution(value="birinci_tekil", source="user_text", label="Ben dili")
    # Kurumsal üçüncü tekil şahıs sesi, sadece belge bize hitap ediyor
    # olarak doğrulandığında belgenin kendi göndericisinden çıkar -- üçüncü
    # taraf bir belgenin varlığı kendi üslubumuz hakkında hiçbir şey söylemez.
    if evidence.party.relation == "reply_to_us" and evidence.fields.get("gonderen_kurum"):
        return SlotResolution(value="kurumsal", source="document_reply", label="Kurumsal dil")
    return None


def _resolve_kapanis(
    evidence: BriefEvidence, known: dict[str, SlotResolution]
) -> Optional[SlotResolution]:
    has_arz = bool(re.search(r"\barz\b", evidence.normalized_text))
    has_rica = bool(re.search(r"\brica\b", evidence.normalized_text))
    if has_arz and has_rica:
        return SlotResolution(
            value="arz_ve_rica_ederim", source="user_text", label="Arz ve rica ederim"
        )
    if has_arz:
        return SlotResolution(value="arz_ederim", source="user_text", label="Arz ederim")
    if has_rica:
        return SlotResolution(value="rica_ederim", source="user_text", label="Rica ederim")

    # Açık bir kapanış kelimesi yok -- muhatabın bu aynı geçişte zaten
    # çözdüğü veya önerdiği her neyse ondan zayıf bir hiyerarşi tahminine
    # geri düş (kapanis'in önceliği onu muhataptan sonraya koyar, bkz.
    # SLOT_CATALOG).
    muhatap = known.get("muhatap")
    if muhatap and any(
        keyword in normalize(muhatap.value) for keyword in _AUTHORITY_KEYWORDS
    ):
        return SlotResolution(value="arz_ederim", source="user_text", label="Arz ederim", confident=False)
    return None


#: Slot başına bir çözümleyici, yalnızca prior-brief devri (``resolve_brief``
#: içinde önce, tek tip olarak kontrol edilir) onu zaten cevaplamamışsa
#: denenir. Bu haritada bulunmaması -- imza/sayi -- "asla çıkarılmaz,
#: yalnızca kullanıcı tarafından cevaplanır ya da Sen karar ver'e bırakılır"
#: anlamına gelir. Her çözümleyici ayrıca `known`'ı da alır; bu aynı geçişte
#: daha önce çözülmüş slotlardır (`SLOT_CATALOG` öncelik sırasında) --
#: `kapanis` hiyerarşi tahmini için `known["muhatap"]`'ı okur.
_SLOT_RESOLVERS: dict[
    str, Callable[[BriefEvidence, dict[str, SlotResolution]], Optional[SlotResolution]]
] = {
    "yazisma_turu": _resolve_yazisma_turu,
    "yazan_taraf": _resolve_yazan_taraf,
    "muhatap": _resolve_muhatap,
    "anlatim": _resolve_anlatim,
    "kapanis": _resolve_kapanis,
}


def resolve_brief(
    input_text: str,
    classification: Optional[dict[str, Any]] = None,
    prior_brief: Optional[dict[str, Any]] = None,
    party: Optional[PartyContext] = None,
) -> BriefResolution:
    """Her yazım stili slotunu çöz, yalnızca bilinmeyen hakkında sor.

    Bilerek deterministik ve LLM'siz: brief gate gerçek bir
    ``interrupt()``'tır (bkz. ``app.ai.workflows.planning_graph.brief_gate_node``),
    devam edildiğinde kendi düğümünü tekrar oynatır ve soru kümesinin hash'i
    frontend'in interrupt'ı üzerinde tekilleştirme yaptığı şeydir -- bu
    yolda pin'lenmemiş bir model çağrısı, o hash'i (ve soruların kendisini)
    ilk soru ile devam etme arasında tekrarlanamaz kılardı. Ayrıca ~30
    saniyelik taslak üretiminin doğrudan önünde durur; burada ikinci bir
    model sıçraması, bir avuç regex ve derlenmiş bir kelime dağarcığının
    zaten yaptığı bir iş için görünür bir gecikme gerilemesidir -- "X ekibi
    olarak" bir yüzey deseni sorunu, bir semantik sorunu değil.

    Args:
        input_text: Kullanıcının bu turdaki mesajı.
        classification: Bir belge eklenmişse belge-analizi sonucu. Onun
            ``fields.muhatap``/``fields.gonderen_kurum``'u, bir belgeye
            yanıt turu için rol-tersine çevirme kuralını destekler -- ama
            yalnızca ``party.relation == "reply_to_us"`` belgenin gerçekten
            bize hitap ettiğini doğruladığında (bkz.
            ``app.ai.identity.parties.resolve_party_context``); bize hitap
            ettiğini doğrulayamadığımız bir belge (bir özgeçmiş, üçüncü
            taraf bir rapor, veya kontrol edecek hiçbir öz-kimlik
            yapılandırılmamış) tersine çevirmeyi asla tetiklemez.
        prior_brief: Aynı oturumdaki daha önceki bir turdan, varsa,
            ``SessionFocus.writing_brief``. Taşıdığı her slot zaten
            cevaplanmış sayılır; bu da bir oturumun 2. ve sonraki turlarını
            sessiz yapan şeydir.
        party: Bu turun çözülen taraf bağlamı (bkz.
            ``app.ai.identity.parties.resolve_party_context``). Bilinmeyen/
            nötr bir bağlama varsayılan olur -- aşağıdaki her taraf-farkında
            dal bir no-op olur ve çözümleme bu parametreden önce var olan
            tamamen metinsel sezgilere geri düşer.

    Returns:
        Çözülmüş slotlar artı (öncelik sırasına göre sıralanmış, sınırlı)
        kalan sorular listesi -- her biri, bir çözümleyicinin düşük güvenli
        bir tahmini olduğunda önerilen bir seçenek taşır (bkz. modül
        docstring'inin üç katmanlı ayrımı).
    """
    fields = _coerce_fields(classification or {})
    evidence = BriefEvidence(
        raw_text=input_text or "",
        normalized_text=normalize(input_text or ""),
        fields=fields,
        prior_brief=dict(prior_brief or {}),
        party=party or _UNKNOWN_PARTY,
    )

    resolved: dict[str, SlotResolution] = {}
    suggested: dict[str, SlotResolution] = {}
    #: resolved ∪ suggested, öncelik sırasında, böylece sonraki bir
    #: çözümleyici (kapanis) daha önceki bir slotun sonucunu her iki
    #: durumda da okuyabilir.
    known: dict[str, SlotResolution] = {}

    for spec in SLOT_CATALOG:
        prior_value = evidence.prior_brief.get(spec.key)
        if prior_value:
            resolution = SlotResolution(
                value=str(prior_value), source="prior_brief", label=str(prior_value)
            )
            resolved[spec.key] = resolution
            known[spec.key] = resolution
            continue

        resolver = _SLOT_RESOLVERS.get(spec.key)
        resolution = resolver(evidence, known) if resolver else None
        if resolution is not None and resolution.confident:
            resolved[spec.key] = resolution
            known[spec.key] = resolution
        elif resolution is not None:
            suggested[spec.key] = resolution
            known[spec.key] = resolution
        elif not spec.required:
            # Çıkarılacak hiçbir şeyi olmayan isteğe bağlı bir slot,
            # MAX_BRIEF_QUESTIONS slotlarından biri için yarışmak yerine
            # doğrudan "Sen karar ver"e varsayılan olur -- required=False
            # "üzerinde asla bloklamaya değmez" demektir, "yine de sor ama
            # atlamalarına izin ver" değil. Bu olmadan, imza/sayi (hiç
            # çözümleyicisi olmayan) her zaman çözülmemiş kalır ve gerçekten
            # bilinmeyen, zorunlu bir slotu dışarı itebilir, ya da her
            # zorunlu gerçeğin zaten bilindiği bir turda gate'i açabilirdi.
            default = SlotResolution(value=AUTO_ANSWER, source="default", label="Sen karar ver")
            resolved[spec.key] = default
            known[spec.key] = default

    unresolved = sorted(
        (spec for spec in SLOT_CATALOG if spec.key not in resolved),
        key=lambda spec: spec.priority,
    )[:MAX_BRIEF_QUESTIONS]
    questions = tuple(spec.to_prompt_question(suggested.get(spec.key)) for spec in unresolved)

    return BriefResolution(resolved=resolved, questions=questions)


def _display_value(key: str, value: str) -> str:
    """Bir slug cevabını (örn. ``"arz_ederim"``) Türkçe etiketine çevir.

    Serbest metin cevaplarının (elle yazılmış bir ad, bir kurum) eşleşen
    bir seçeneği yoktur ve değişmeden döndürülür.
    """
    spec = _SLOT_BY_KEY.get(key)
    if spec is None:
        return value
    for option in spec.options:
        if option.value == value:
            return option.label
    return value


def format_writing_brief(answers: dict[str, str]) -> str:
    """Render the resolved writing brief for the writer's grounding prompt.

    Every slot the writer needs a direction for is stated explicitly,
    including a slot answered ``AUTO_ANSWER`` -- omitting an unknown slot
    reads to the model as "no constraint", which is the exact failure mode
    this module exists to close (see the module docstring).

    Args:
        answers: Final slot values -- resolved automatically, supplied by
            the human at the brief gate, or ``AUTO_ANSWER``.

    Returns:
        The brief section's Turkish text, or an explanatory placeholder if
        no answers were supplied at all (a document-less, gate-disabled
        turn where nothing tried to resolve anything).
    """
    if not answers:
        return "Yazım briefi oluşturulmadı; taslak dili genel resmî üslupla yazılmalıdır."

    lines: list[str] = []
    for spec in SLOT_CATALOG:
        value = answers.get(spec.key)
        if not value:
            continue
        if value == AUTO_ANSWER:
            lines.append(f"- {spec.header}: (sistem karar verecek)")
            continue
        display = _display_value(spec.key, value)
        if spec.key == "yazan_taraf":
            lines.append(
                f"- Yazıyı Yazan Taraf (gönderen): {display}\n"
                "  → Bu ad ANTET ve İMZA BLOĞUNDA yer alır. Muhatap satırında ASLA yer almaz."
            )
        elif spec.key == "muhatap":
            lines.append(
                f"- Yazının Gönderileceği Makam (muhatap): {display}\n"
                "  → Bu ad YALNIZCA muhatap satırında yer alır."
            )
        else:
            lines.append(f"- {spec.header}: {display}")

    return "\n".join(lines) if lines else format_writing_brief({})
