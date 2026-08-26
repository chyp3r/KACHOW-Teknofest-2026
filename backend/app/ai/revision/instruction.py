"""Kullanıcının revizyon isteğinin deterministik ayrıştırılması.

Bir revize turu asla yeniden sınıflandırma yapmaz ve varsayılan olarak asla
mevzuatı yeniden çekmez (bkz. ``app.ai.workflows.revise``) -- doğrudan aktif
taslak, kullanıcının zaten gördüğü metin üzerinde çalışır. Bu modül ilk,
LLM kullanmayan adımdır: kullanıcının ham talimatını, daha sonraki adımların
(hedefleme, koşullu yeniden çekme, çelişki denetimi) ham metni kendileri
yeniden ayrıştırmadan okuduğu yapılandırılmış bir ``RevisionInstruction``'a
dönüştürür.

Kullanıcının talimatı burada asla yeniden yazılmaz veya yumuşatılmaz --
``raw``, her aşağı akış promptuna kelimesi kelimesine taşınır. Bu modül
yalnızca onun *etrafına* yapı ekler; onu asla düzenlemez.
"""

import re
from dataclasses import dataclass, field
from typing import Literal, Optional, Sequence

from app.ai.verification.draft_verifier import (
    AMOUNT_PATTERN,
    DATE_PATTERN,
    DOCUMENT_NUMBER_PATTERN,
    INSTITUTION_PATTERN,
    LEGISLATION_PATTERN,
)
from app.ai.workflows.intent_scorer import _compile_surface, normalize

Scope = Literal["paragraph", "section", "whole"]
Operation = Literal["tone_formal", "tone_informal", "shorten", "lengthen", "content"]

#: Sabit 9 parçalı resmi mektup biçiminin (bkz. prompts/templates/writer.md)
#: tanınan yapısal parçaları ve onları adlandıran ifadeler. "konu" burada
#: bilinçli olarak yok -- diğer üçünün aksine, çıplak bir "konu" Türkçe'de
#: gerçekten belirsizdir (bkz. `_KONU_HINT_PATTERN`) ve düz bir yüzey listesi
#: yerine kendi, daha dar çözümlemesini alır.
_SECTION_HINTS: dict[str, tuple[str, ...]] = {
    "giris": ("giris", "ilk paragraf", "baslangic paragrafi"),
    "kapanis": ("kapanis", "son paragraf", "arz kismi", "rica kismi"),
    "imza": ("imza", "imza blogu", "imza kismi"),
}
#: `_SECTION_HINTS` (C20) için sol kelime sınırıyla derlenmiş kalıplar --
#: düz bir alt dize testi "imza"nın onunla başlayan ilgisiz bir kelimenin
#: içinde eşleşmesine izin veriyordu; `intent_scorer.ALL_RULES`'ın kendi
#: yüzeyleri için kullandığı aynı derleyici.
_SECTION_HINT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    canonical: tuple(_compile_surface(surface) for surface in surfaces)
    for canonical, surfaces in _SECTION_HINTS.items()
}

#: "konu" ayrı çözümlenir (C20): "konu" üzerinde düz bir alt dize testi,
#: "Bu konuda daha resmi bir dil kullan" ifadesinin (genel bir yorum, mektubun
#: kendi Konu alanını hiç adlandırmıyor) eşleşmesine ve bütün taslak için
#: düşünülmüş bir talimatı yalnızca Konu satırına daraltmasına neden
#: oluyordu. Türkçe'de hal ekleri farkı belirtir: akuzatif ("konuyu",
#: "konusunu" -- doğrudan nesne, "KONU alanını değiştir") alanı ifade eder;
#: lokatif/enstrümantal ("konuda", "konuyla" -- "bu konuyla ilgili") etmez.
#: İlk alternatif, hemen ardına başka bir şey yapışmadığında yalnızca çıplak
#: "konu"yu veya akuzatif ekli bir biçimi eşleştirir (böylece "konuda"
#: isteğe bağlı grup üzerinden eşleşemez); ikincisi, "konu"yu belirli bir
#: alan-adlandıran kelimenin takip ettiği durumları eşleştirir ("konu
#: satırı", "konu başlığı", "konu kısmı", "konu alanı").
_KONU_HINT_PATTERN = re.compile(
    r"\bkonu(?:yu|sunu)?(?=\s|$)|\bkonu\s+(?:satir|basli[gk]|kism|alan)"
)

#: Özellikle *kapanış* paragrafının içindeki ifadeler -- kapanış cümlesi
#: yalnız kendi paragrafında değil, bir paragrafın ortasında da
#: görünebildiğinden "kapanış" bölümünü yalnızca konuma göre değil yapısal
#: olarak bulmak için kullanılır.
_CLOSING_MARKERS = ("arz ederim", "rica ederim", "bilgilerinize sunulur")

_ORDINAL_PATTERN = re.compile(r"(\d+)\s*\.?\s*paragraf")
_ORDINAL_WORDS: dict[str, int] = {
    "ilk": 1, "birinci": 1, "ikinci": 2, "ucuncu": 3, "dorduncu": 4, "son": -1,
}

#: "N. paragrafı düzenle" değil, "bir paragraf ekle" anlamına gelen fiiller
#: (C19). "Metne 2 paragraf daha ekle", "2"yi mevcut bir paragrafın sıra
#: numarası değil, eklenecek yeni paragrafların *sayısı* olarak okur --
#: `_ORDINAL_PATTERN` tek başına ikisini ayırt edemez (ikisi de
#: "\d+ paragraf"), bu yüzden bu, aynı talimatta bu ekleme fiillerinden biri
#: de mevcut olduğunda sayısal sıra numarası okumasını reddeder.
_PARAGRAPH_ADDITION_HINTS = ("ekle", "ilave et", "ilave edilsin", "eklensin")

_OPERATION_HINTS: dict[Operation, tuple[str, ...]] = {
    "tone_formal": ("daha resmi", "resmiyet"),
    "tone_informal": ("daha samimi", "daha sicak"),
    "shorten": ("kisalt", "daha kisa", "ozetle"),
    "lengthen": ("uzat", "daha uzun", "detaylandir", "genislet"),
}

#: ``decompose_instruction`` için bileşik bir talimatı cümle başına
#: parçalara böler. Türkçe bağlaçlar artı olağan cümle sonlandırıcıları --
#: bilinçli olarak dar tutulmuş (yanlış bir bölme yalnızca bir direktife
#: ayrıştırılamayıp düşen bir ekstra parça üretir, bkz.
#: ``decompose_instruction``; kaçırılan bir bölme bütün-taslak kapsamına
#: geri döner, bugünün mevcut güvenli varsayılanı).
_CLAUSE_SPLIT = re.compile(
    r"\s+ve\s+|\s+ayrıca\s+|\s+bir de\s+|\s*;\s*|\n+|(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ])"
)

#: Bir talimatta bulunması, yalnızca bir stil/uzunluk değişikliği istemek
#: yerine normatif içerik (bir kanun, bir kurum, bir belge numarası, bir
#: tutar) tanıtmaya veya ona atıfta bulunmaya çalıştığı anlamına gelen
#: iddia türleri -- bkz. ``needs_reretrieval``.
_NORMATIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    LEGISLATION_PATTERN,
    INSTITUTION_PATTERN,
    DOCUMENT_NUMBER_PATTERN,
    DATE_PATTERN,
    AMOUNT_PATTERN,
)


@dataclass(frozen=True)
class EditDirective:
    """(Muhtemelen bileşik) bir talimattan çıkarılan tek bir atomik düzenleme.

    Attributes:
        scope: Bu direktifin taslağın hangi kısmını hedeflediği.
        operation: Ne tür bir değişiklik istediği. Yalnızca bilgi amaçlı.
        section_hint: ``scope == "section"`` olduğunda, tanınan bir yapısal parça adı.
        ordinal: ``scope == "paragraph"`` olduğunda, 1'den başlayan bir
            paragraf indeksi (``-1`` "son" demektir).
        raw: Bu direktifin kendi cümlesi, değiştirilmeden.
        order: Kararlı sağdan-sola uygulama için talimatın direktifleri
            arasındaki konum (bkz. ``locate_target``'ın çağıranı).
    """

    scope: Scope
    operation: Operation
    section_hint: Optional[str]
    ordinal: Optional[int]
    raw: str
    order: int


@dataclass(frozen=True)
class RevisionInstruction:
    """Kullanıcının revize isteği, bir kapsam ve bir işleme ayrıştırılmış.

    Attributes:
        scope: Talimatın taslağın hangi kısmını hedeflediği.
        operation: Ne tür bir değişiklik istediği. Yalnızca bilgi amaçlı --
            hangi promptun çalıştığını değiştirmez, yalnızca bir çağıranın
            loglayabileceği veya gösterebileceği şeyi; model ``raw``'ı
            doğrudan okur.
        section_hint: ``scope == "section"`` olduğunda, tanınan bir yapısal
            parça adı (bkz. ``_SECTION_HINTS``).
        ordinal: ``scope == "paragraph"`` olduğunda, 1'den başlayan bir
            paragraf indeksi (``-1`` "son" demektir).
        raw: Talimat metni, prompt için değiştirilmeden.
        directives: Talimatın atomik düzenlemelerine ayrıştırılmış hali
            (bkz. ``decompose_instruction``). Her zaman en az bir giriş
            içerir; daha fazla bölünemediğinde ``raw``'ı talimatın
            tamamıdır -- ``scope="whole"``'un temsil ettiği aynı güvenli
            varsayılan.
        introduces_normative_content: Talimatın bir kanuna, maddeye, kuruma,
            belge numarasına, tarihe veya tutara atıfta bulunup
            bulunmadığı -- yani mevzuatın yeniden çekilmesinin dayanak
            oluşturmak için gerekebileceği bir şey istemesi (bkz.
            ``needs_reretrieval``).
        normative_tokens: ``introduces_normative_content``'i doğru yapan
            spesifik token'lar.
    """

    scope: Scope
    operation: Operation
    section_hint: Optional[str]
    ordinal: Optional[int]
    raw: str
    directives: tuple[EditDirective, ...] = field(default_factory=tuple)
    introduces_normative_content: bool = False
    normative_tokens: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TargetSpan:
    """Yeniden yazımın sınırlanması gereken taslaktaki bir karakter aralığı."""

    start: int
    end: int
    text: str


def _parse_one(raw: str) -> tuple[Scope, Operation, Optional[str], Optional[int]]:
    """Tek bir cümleden scope/operation/section_hint/ordinal çıkarır."""
    normalized = normalize(raw)

    section_hint: Optional[str] = None
    if _KONU_HINT_PATTERN.search(normalized):
        section_hint = "konu"
    else:
        for canonical, patterns in _SECTION_HINT_PATTERNS.items():
            if any(pattern.search(normalized) for pattern in patterns):
                section_hint = canonical
                break

    ordinal: Optional[int] = None
    match = _ORDINAL_PATTERN.search(normalized)
    if match and not any(hint in normalized for hint in _PARAGRAPH_ADDITION_HINTS):
        ordinal = int(match.group(1))
    else:
        padded = f" {normalized} "
        for word, value in _ORDINAL_WORDS.items():
            if f" {word} paragraf" in padded:
                ordinal = value
                break

    operation: Operation = "content"
    for op, surfaces in _OPERATION_HINTS.items():
        if any(surface in normalized for surface in surfaces):
            operation = op
            break

    if ordinal is not None:
        scope: Scope = "paragraph"
    elif section_hint is not None:
        scope = "section"
    else:
        scope = "whole"

    return scope, operation, section_hint, ordinal


def _normative_tokens(text: str) -> tuple[str, ...]:
    """``text``'teki her normatif-içerik token'ı (kanun/madde/kurum/tarih/tutar);
    tekilleştirilmiş ama sıra korunmuş."""
    seen: dict[str, None] = {}
    for pattern in _NORMATIVE_PATTERNS:
        for match in pattern.findall(text):
            value = (match if isinstance(match, str) else match[0]).strip()
            if value:
                seen.setdefault(value, None)
    return tuple(seen)


def decompose_instruction(instruction: str) -> tuple[EditDirective, ...]:
    """Bileşik bir talimatı atomik düzenleme direktiflerine ayırır.

    Args:
        instruction: Kullanıcının ham revize isteği; muhtemelen aynı anda
            birkaç farklı değişiklik istiyor ("Konuyu değiştir ve son
            paragrafı kısalt.").

    Returns:
        Tanınan her cümle için bir ``EditDirective``. Ne bir bölüm ne de
        bir paragraf adlandıran ve hiçbir işlem yüzeyi olmayan bir cümle
        gürültü olarak düşürülür (kendi başına bir bağlaç, örn. başıboş bir
        "ve"). Bu, sıfır veya bir direktif bıraktığında, bunun yerine
        *orijinal talimatın tamamını* taşıyan tek bir ``scope="whole"``
        direktifi döndürülür -- ayrıştırma bir hedefleme optimizasyonudur,
        çağıranların bölünecek bir şey bulamadığında özel durum olarak ele
        alması gereken bir şey değildir.
    """
    fragments = [frag.strip() for frag in _CLAUSE_SPLIT.split(instruction) if frag.strip()]

    directives: list[EditDirective] = []
    for order, fragment in enumerate(fragments):
        scope, operation, section_hint, ordinal = _parse_one(fragment)
        if scope == "whole" and operation == "content":
            # Bu parçanın kendisinde ne bir konum ne de bir işlem
            # tanınmadı -- bir direktif değil, sadece bağlayıcı doku.
            continue
        directives.append(
            EditDirective(
                scope=scope, operation=operation, section_hint=section_hint,
                ordinal=ordinal, raw=fragment, order=order,
            )
        )

    if len(fragments) > 1 and len(directives) < len(fragments):
        # En az bir bağlaçla ayrılmış cümle ne bir bölüm/paragraf ne de bir
        # işlem adlandırdı -- örn. "Konuyu değiştir ve muhatap Ankara
        # Valiliği" içindeki "muhatap Ankara Valiliği". O cümle başka bir
        # direktifin kendi bulunmuş aralığının içine binemez (bir
        # direktifin promptu kendi aralığıyla sınırlıdır -- bkz.
        # _build_directive_prompt), bu yüzden aksi halde sessizce
        # düşürülürdü: bu, Görev 2'nin "bilgi kısmı hiçbir yere
        # yazılmıyor" hatasıydı. *Birleştirilmiş* metni tek bir
        # section_hint için yeniden ayrıştırmak (aşağıdaki eski yedek) da
        # bir düzeltme değil -- yalnızca bir cümleden dar bir konum yeniden
        # keşfedebilir ve bütün bileşik isteği o tek aralığa yanlış
        # uygulayabilir. Güvenli varsayılan: bulunmuş direktiflere tam
        # olarak ayrıştırılamayan çok cümleli bir talimat, her cümlenin
        # kendi metnini (`instruction`, değiştirilmeden) taşıyan tek bir
        # bütün-taslak yeniden yazıma geri döner; böylece istenen hiçbir
        # şey kaybolmaz.
        return (
            EditDirective(
                scope="whole", operation="content", section_hint=None,
                ordinal=None, raw=instruction, order=0,
            ),
        )

    if len(directives) <= 1:
        scope, operation, section_hint, ordinal = _parse_one(instruction)
        return (
            EditDirective(
                scope=scope, operation=operation, section_hint=section_hint,
                ordinal=ordinal, raw=instruction, order=0,
            ),
        )

    return tuple(directives)


def parse_revision_instruction(instruction: str) -> RevisionInstruction:
    """Bir revize isteğinden bir kapsam ve bir işlem çıkarır.

    Taslağın kendi bilinen, sabit yapısı üzerinde deterministik anahtar
    kelime eşleştirmesi -- genel bir NLU ayrıştırması değil. Ne bir paragraf
    numarası ne de tanınan bir bölüm adlandıran bir talimat, güvenli
    varsayılan olan ``scope="whole"``'a çözümlenir: hangi kısmın kastedildiğine
    dair bir tahmin yerine yine tek çağrılı, tam bir yeniden yazım.

    Args:
        instruction: Kullanıcının revize isteği.

    Returns:
        Atomik direktiflere ayrıştırılmış hali ve normatif içeriğe atıfta
        bulunup bulunmadığı dahil, ayrıştırılmış talimat.
    """
    scope, operation, section_hint, ordinal = _parse_one(instruction)
    tokens = _normative_tokens(instruction)

    return RevisionInstruction(
        scope=scope, operation=operation, section_hint=section_hint,
        ordinal=ordinal, raw=instruction,
        directives=decompose_instruction(instruction),
        introduces_normative_content=bool(tokens),
        normative_tokens=tokens,
    )


def needs_reretrieval(instruction: RevisionInstruction) -> bool:
    """Bu revizyonun yeni bir mevzuat aramasını tetiklemesi gerekip gerekmediği.

    Talimatın kendisi, taslağın donmuş bağlamının zaten kapsamıyor olabileceği
    bir kanun, madde, kurum, tarih veya tutar adlandırdığında True -- saf bir
    ton/uzunluk isteği asla bunu yapmaz. Bkz. tek çağıranı olan
    ``app.ai.revision.retrieval.maybe_extend_context``.

    Args:
        instruction: Ayrıştırılmış talimat.

    Returns:
        Koşullu bir yeniden çekmenin çalışması gerekip gerekmediği.
    """
    return instruction.introduces_normative_content


def _split_paragraphs(draft: str) -> list[tuple[int, int]]:
    """Boş satırla ayrılmış her paragrafın (start, end) karakter ofsetlerini döndürür."""
    return [(m.start(), m.end()) for m in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", draft)]


#: Taslağın kendi sabit üst veri başlığı alan etiketleri (bkz. writer.md'nin
#: numaralı yapısı, alanlar 2-6: Sayı/Tarih/Konu/Muhatap/İlgi/Ekler) --
#: app.ai.verification.placeholders._HEADER_LINE_PATTERN'ın kendi, ilgisiz
#: yedeği için tanıdığı aynı etiket kümesi; bu ikisi de aynı başlık
#: bloğunda oturabildiğinden İlgi/Ekler ile genişletilmiş.
_HEADER_FIELD_LINE = re.compile(
    r"^\s*(Sayı|Sayi|Tarih|Konu|Muhatap|İlgi|Ilgi|Ekler)\s*:", re.IGNORECASE
)


def _is_header_paragraph(text: str) -> bool:
    """Boş satırla ayrılmış bir bloğun saf mektup üst verisi olup olmadığı;
    bir kullanıcının "ilk paragraf"/"giriş" derken asla kastetmediği şey.

    Bunun kapattığı hata: tipik bir taslağın "Konu:"/"Sayı:"/"Tarih:"
    satırları arasında *hiç* boş satır olmadan ardışık satırlarda oturur
    (bkz. writer.md'nin sabit yapısı), bu yüzden ``_split_paragraphs``
    bunları -- filtrelenmemiş halde -- tam olarak "1. paragrafı sil"/
    "girişi değiştir"in doğal olarak işaret ettiği indeks 0'a düşen tek bir
    blokta gruplar. Bir mektubun açılışını düzenlemesini isteyen hiç kimse
    üst veri başlığını kastetmez; filtrelenmemiş haliyle reviser'a bu blok,
    ilgisiz bir gövde düzenlemesi için kendi yeniden yazım hedefi olarak
    verildi ve düz metin yerine bir "Sayı: ..." satırına uygulanınca çoğu
    zaman onu bozar veya tamamen düşürürdü -- bunun kapattığı somut "sayıyı
    siliyor" belirtisi. Baştaki bir antet bloğu ("T.C.\\nKURUM ADI", hiç
    etiketli alan yok) da aynı şekilde, her antetin başladığı literal
    "T.C." işaretiyle yakalanır.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.upper().startswith("T.C."):
        return True
    lines = [line for line in text.splitlines() if line.strip()]
    return bool(lines) and all(_HEADER_FIELD_LINE.match(line) for line in lines)


def _body_paragraphs(draft: str, paragraphs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Yalnızca sıra/"giriş" hedeflemesi için, saf üst veri bloğu düşürülmüş
    ``paragraphs`` -- ``konu``/``kapanis``/``imza`` bölüm ipuçları, ``konu``
    özellikle başlığın kendi Konu satırını bulmak anlamına geldiğinden
    tam listeyi filtrelenmeden taramaya devam eder."""
    body = [span for span in paragraphs if not _is_header_paragraph(draft[span[0] : span[1]])]
    return body or paragraphs


def _locate_one(
    draft: str, paragraphs: list[tuple[int, int]], *,
    scope: Scope, section_hint: Optional[str], ordinal: Optional[int],
) -> Optional[TargetSpan]:
    if scope == "paragraph" and ordinal is not None:
        body = _body_paragraphs(draft, paragraphs)
        index = ordinal - 1 if ordinal > 0 else len(body) - 1
        if 0 <= index < len(body):
            start, end = body[index]
            return TargetSpan(start, end, draft[start:end])
        return None

    if scope == "section" and section_hint:
        if section_hint == "imza":
            start, end = paragraphs[-1]
            return TargetSpan(start, end, draft[start:end])
        if section_hint == "kapanis":
            for start, end in paragraphs:
                if any(marker in normalize(draft[start:end]) for marker in _CLOSING_MARKERS):
                    return TargetSpan(start, end, draft[start:end])
            return None
        if section_hint == "konu":
            for start, end in paragraphs:
                if normalize(draft[start:end]).startswith("konu"):
                    return TargetSpan(start, end, draft[start:end])
            return None
        if section_hint == "giris":
            body = _body_paragraphs(draft, paragraphs)
            start, end = body[0]
            return TargetSpan(start, end, draft[start:end])

    return None


def locate_target(
    draft: str, instruction: "RevisionInstruction | EditDirective"
) -> Optional[TargetSpan]:
    """``instruction``'ın kesin olarak adlandırdığı karakter aralığını bulur.

    Args:
        draft: Güncel taslak metni.
        instruction: Ayrıştırılmış talimat veya ondan tek bir direktif --
            ikisi de aynı ``scope``/``section_hint``/``ordinal`` üçlüsünü taşır.

    Returns:
        Hedef aralık, veya kapsam ``"whole"`` olduğunda ya da adlandırılan
        paragraf/bölüm bulunamadığında ``None`` -- çağıranlar ``None``'ı
        tahmin etmek yerine "bütün taslağı yeniden yaz" olarak ele alır.
    """
    paragraphs = _split_paragraphs(draft)
    if not paragraphs:
        return None
    return _locate_one(
        draft, paragraphs,
        scope=instruction.scope, section_hint=instruction.section_hint,
        ordinal=instruction.ordinal,
    )


#: Yeniden yazılan/hedef uzunluk oranının bu değerinin üzerinde, modelin
#: çıktısı istenen kapsamı yok sayıp hedeflenen aralıktan çok daha fazlasını
#: yeniden ürettiği gibi görünür -- bunu olduğu gibi eklemek, yalnızca hedefi
#: değiştirmek yerine hedefin kendi sonundan sonra gelen her şeyi ikiye katlar.
_SCOPE_OVERRUN_LENGTH_RATIO = 3.0

#: Yukarıdaki orana ek olarak, bunun "bu paragraf öncekinden çok daha uzun
#: oldu" yerine "model her şeyi yeniden üretti" olarak sayılması için
#: yeniden yazılan metnin *bütün taslağın* kendi uzunluğunun ne kadarına
#: ulaşması gerektiği -- ikisini birlikte ayırt eden şey budur.
_SCOPE_OVERRUN_DRAFT_FRACTION = 0.7


def resolve_merge_target(
    target: Optional[TargetSpan], rewritten: str, source_draft: str
) -> Optional[TargetSpan]:
    """Bir direktifin yeniden yazımının kendi kapsamını yok saymasını tespit eder (C22).

    Bir paragrafa veya bölüme kapsamlanan bir direktif, modele kendi
    promptunda yalnızca o bölümün yeni metnini döndürmesini söyler (bkz.
    ``revise_graph._build_directive_prompt``'ın ``scope_rule``'u). Bunu yok
    sayıp yine de bütün taslağı yeniden üreten bir model, hem değiştirmesi
    istenen hedeften çok daha uzun *hem de* bütün taslağın kendi uzunluğuna
    yakın bir metin üretir -- bunu orijinal dar aralıkta ``_merge`` ile
    eklemek, gerçek olanın ortasına bütün bir ekstra taslak yapıştırır ve
    içeriği değiştirmek yerine kabaca ikiye katlar.

    Args:
        target: Direktifin kendi bulunmuş aralığı, veya ``None`` (zaten
            bütün-taslak kapsamı, bu yüzden tanım gereği aşılacak bir şey yok).
        rewritten: Modelin bu direktif için ham çıktısı.
        source_draft: Bu direktifin kapsamlandığı tam taslak.

    Returns:
        Olağan durumda ``target`` değişmeden, veya bir aşım tespit
        edildiğinde ``None`` -- çağıranın kendi ``_merge`` çağrısı, o zaman
        eklemek yerine hiç bulunmuş aralığı olmayan bir direktifin zaten
        aldığı aynı bütün-taslak-değiştirme yolunu alır.
    """
    if target is None:
        return None

    target_length = len(target.text.strip())
    if target_length == 0:
        return target

    rewritten_length = len(rewritten.strip())
    if rewritten_length < target_length * _SCOPE_OVERRUN_LENGTH_RATIO:
        return target

    draft_length = len(source_draft.strip())
    if draft_length > 0 and rewritten_length >= draft_length * _SCOPE_OVERRUN_DRAFT_FRACTION:
        return None
    return target


def spans_overlap(targets: Sequence[Optional[TargetSpan]]) -> bool:
    """Verilen hedef aralıklardan herhangi ikisinin çakışıp çakışmadığı (C5).

    Çok-direktifli sağdan-sola birleştirme (bkz.
    ``revise_graph.rewrite_node``), her direktifin kendi aralığının orijinal
    taslağa karşı geçerli, ayrık bir aralık olarak kaldığını varsayar -- bir
    çakışma bu varsayımı bozar, bir direktifin eklemesinin bir diğerinin
    ofsetlerini bozmasına veya aralarındaki paylaşılan metni
    çoğaltmasına/düşürmesine izin verir.

    Args:
        targets: Her direktifin kendi bulunmuş aralığı. Bir ``None`` girdi
            (bulunamayan bir direktif) hiçbir zaman kendisi bir çakışmanın
            parçası değildir -- bu durum, bu hiç çağrılmadan önce her
            hedefin ``None`` olmamasını gerektirerek zaten ele alınır.

    Returns:
        Herhangi iki ``None`` olmayan aralık kesiştiğinde True.
    """
    spans = sorted((t.start, t.end) for t in targets if t is not None)
    return any(spans[i][1] > spans[i + 1][0] for i in range(len(spans) - 1))


def _merge(source_draft: str, target: Optional[TargetSpan], rewritten: str) -> str:
    """Yeniden yazılan metni geri ekler. Dokunulmamış baş ve son kısımlar,
    model tarafından yeniden üretilmek yerine doğrudan orijinal metinden
    gelir, bu yüzden hedef aralığın dışında istenmeyen bir değişiklik,
    sonradan kontrol edilecek bir şey olmaktan çıkıp yapısal olarak
    imkansız hale gelir."""
    rewritten = rewritten.strip()
    if target is None:
        return rewritten
    return f"{source_draft[:target.start]}{rewritten}{source_draft[target.end:]}"
