import re
import unicodedata
from typing import Any

from app.ai.workflows.intent_scorer import _compile_surface
from app.core.enums.correspondence_type import CorrespondenceType

CORRESPONDENCE_TYPE_LABELS = {
    CorrespondenceType.COVER_LETTER: "Üst yazı",
    CorrespondenceType.RESPONSE_LETTER: "Cevap yazısı",
    CorrespondenceType.INFORMATION_NOTICE: "Bilgilendirme metni",
    CorrespondenceType.OTHER_OFFICIAL: "Diğer resmî yazışma",
}

CORRESPONDENCE_TYPE_GUIDANCE = {
    CorrespondenceType.COVER_LETTER: (
        "İletilen ek veya dayanak belgeyi, gönderim amacını ve beklenen işlemi kısa ve "
        "hiyerarşik biçimde belirt. Kaynakta bulunmayan ek, sayı veya makam üretme."
    ),
    CorrespondenceType.RESPONSE_LETTER: (
        "Gelen evraktaki talep veya soruyu doğrudan karşıla; dayanak ve sonucu açıkça "
        "belirt. Kaynakla desteklenmeyen karar, taahhüt veya işlem sonucu üretme."
    ),
    CorrespondenceType.INFORMATION_NOTICE: (
        "Bilgiyi tarafsız, anlaşılır ve maddi olgulara bağlı biçimde aktar; kapsamı ve "
        "varsa doğrulanmış sonraki adımları belirt. Talep edilmemiş karar dili kullanma."
    ),
    CorrespondenceType.OTHER_OFFICIAL: (
        "Belgenin amacıyla uyumlu, esnek fakat resmî bir yapı kullan. Tür belirsizliğini "
        "yeni olgular üreterek kapatma; nihai kullanım öncesinde insan incelemesi iste."
    ),
}

CORRESPONDENCE_TYPE_ALIASES = {
    CorrespondenceType.COVER_LETTER: {
        "cover letter",
        "cover_letter",
        "ust yazi",
        "ustyazi",
    },
    CorrespondenceType.RESPONSE_LETTER: {
        "answer letter",
        "cevap",
        "cevap yazisi",
        "response",
        "response letter",
        "response_letter",
        "yanit",
        "yanit yazisi",
    },
    CorrespondenceType.INFORMATION_NOTICE: {
        "bilgi notu",
        "bilgilendirme",
        "bilgilendirme metni",
        "information notice",
        "information_notice",
    },
    CorrespondenceType.OTHER_OFFICIAL: {
        "alternatif resmi yazisma",
        "diger resmi yazisma",
        "other official",
        "other_official",
        "resmi yazi",
    },
}

#: Yöne duyarlı tür (genre) yüzeyleri; kullanıcının kendi taslak isteğine
#: karşı eşleştirilir (orkestratör boilerplate'ine karşı asla -- bkz.
#: ``resolve_correspondence_type``'in ``user_request`` argümanı). Her giriş
#: ``(surface, type, sub_genre_label)`` biçimindedir. Bir sub_genre etiketi,
#: dört spec'lenmiş CorrespondenceType değerinden biri olmayan belirli bir
#: belge türüdür ("itiraz dilekçesi") -- yine de OTHER_OFFICIAL'a çözümlenir,
#: ama etiketin kendisi writer prompt'una taşınır (bkz.
#: ``format_correspondence_profile``), böylece çıktı genel bir "diğer resmî
#: yazışma" yerine gerçekten o türe göre şekillenir.
#:
#: Yalın bir tür ismini ("dilekçe") daha uzun ve daha özgül olarak geride
#: bırakan zıt-yön yüzeylerini ("dilekçeye cevap") içerir --
#: "dilekçeye cevap yaz", bir dilekçeye *yanıt vermek* anlamına gelir
#: (bir response_letter), "dilekçe yaz"ın (birini yazmak, bir
#: other_official alt türü) tam tersidir. Eşleştirme her yüzeyi en uzundan
#: başlayarak dener (bkz. ``match_genre``), böylece daha özgül ifade,
#: içerdiği alt dizeye karşı her zaman kazanır ve ayrı bir "karşı-sinyal"
#: takibine gerek kalmaz.
GENRE_SURFACES: tuple[tuple[str, CorrespondenceType, str], ...] = (
    # Zıt-yön: "bir dilekçe/itiraz/başvuruya yanıt vermek" bir
    # response_letter'dır, dilekçenin kendisi değil.
    ("dilekceye cevap", CorrespondenceType.RESPONSE_LETTER, ""),
    ("dilekceyi yanitla", CorrespondenceType.RESPONSE_LETTER, ""),
    ("itiraza cevap", CorrespondenceType.RESPONSE_LETTER, ""),
    ("basvuruya cevap", CorrespondenceType.RESPONSE_LETTER, ""),
    ("talebe cevap", CorrespondenceType.RESPONSE_LETTER, ""),
    # Çekirdek tür isimleri (CORRESPONDENCE_TYPE_ALIASES ile senkron
    # tutulur; farklı öncelik kurallarına sahip ayrı bir arama yerine,
    # aşağıdaki alt türlerle aynı en-uzundan-başlayan geçişe katılsınlar
    # diye burada yeniden listelenir).
    ("cevap yazisi", CorrespondenceType.RESPONSE_LETTER, ""),
    ("yanit yazisi", CorrespondenceType.RESPONSE_LETTER, ""),
    ("cevabini yaz", CorrespondenceType.RESPONSE_LETTER, ""),
    ("ust yazi", CorrespondenceType.COVER_LETTER, ""),
    ("bilgilendirme metni", CorrespondenceType.INFORMATION_NOTICE, ""),
    ("bilgi notu", CorrespondenceType.INFORMATION_NOTICE, ""),
    ("duyuru metni", CorrespondenceType.INFORMATION_NOTICE, ""),
    # Alt türler: dört spec'lenmiş türün dışında, serbest metin olarak taşınır.
    ("itiraz dilekcesi", CorrespondenceType.OTHER_OFFICIAL, "itiraz dilekçesi"),
    ("basvuru dilekcesi", CorrespondenceType.OTHER_OFFICIAL, "başvuru dilekçesi"),
    ("sikayet dilekcesi", CorrespondenceType.OTHER_OFFICIAL, "şikayet dilekçesi"),
    ("muvafakatname", CorrespondenceType.OTHER_OFFICIAL, "muvafakatname"),
    ("taahhutname", CorrespondenceType.OTHER_OFFICIAL, "taahhütname"),
    ("vekaletname", CorrespondenceType.OTHER_OFFICIAL, "vekâletname"),
    ("muzekkere", CorrespondenceType.OTHER_OFFICIAL, "müzekkere"),
    ("olur yazisi", CorrespondenceType.OTHER_OFFICIAL, "olur yazısı"),
    ("gorus yazisi", CorrespondenceType.OTHER_OFFICIAL, "görüş yazısı"),
    ("davet yazisi", CorrespondenceType.OTHER_OFFICIAL, "davet yazısı"),
    ("teblig yazisi", CorrespondenceType.OTHER_OFFICIAL, "tebliğ yazısı"),
    ("tutanak", CorrespondenceType.OTHER_OFFICIAL, "tutanak"),
    ("dilekce", CorrespondenceType.OTHER_OFFICIAL, "dilekçe"),
)

#: ``GENRE_SURFACES``'in en-uzun-yüzey-önce sıralanmış hâli; her çağrıda
#: yeniden sıralamak yerine import zamanında bir kez hesaplanır.
_GENRE_SURFACES_BY_LENGTH = tuple(
    sorted(GENRE_SURFACES, key=lambda entry: len(entry[0]), reverse=True)
)

#: ``OTHER_OFFICIAL``'a çözümlenen ama o türün "brief'te bulunmayan
#: tamamlayıcı bilgileri genel kurumsal bilgi birikiminle tamamlayabilirsin"
#: müsamahasını (C16) asla almaması gereken alt tür etiketleri -- bunlar
#: kataloğun hukuki açıdan en ağır belgeleridir (yazılı muvafakat, resmî bir
#: taahhüt, bir vekâletname, resmî bir tutanak/kayıt, kişisel bir dilekçe);
#: burada uydurulmuş bir olgu, sıradan bir üst yazının bilinmeyen
#: boilerplate'inden çok daha büyük bir sorundur. Beşinci bir
#: ``CorrespondenceType`` değeri yerine kendi kümesinde tutulur: *tür*
#: (yapı, dört spec'lenmiş genre) ve *sıkılık* (uydurmanın tolere edilip
#: edilmeyeceği) ayrı sorulardır ve bu alt türlerin her biri zaten
#: ``OTHER_OFFICIAL``'ın esnek yapısına ihtiyaç duyar -- takip etmemesi
#: gereken şey özellikle müsamahadır.
STRICT_SUB_GENRES: frozenset[str] = frozenset(
    {
        "itiraz dilekçesi",
        "başvuru dilekçesi",
        "şikayet dilekçesi",
        "dilekçe",
        "muvafakatname",
        "taahhütname",
        "vekâletname",
        "tutanak",
    }
)


def is_strict_sub_genre(sub_genre: str) -> bool:
    """``sub_genre``'ın ``OTHER_OFFICIAL``'a çözümlenmesine rağmen sıkı kalıp kalmayacağı.

    Args:
        sub_genre: Serbest metin alt tür etiketi (bkz.
            ``resolve_correspondence_type``'in dönüş değeri), ya da bir
            çekirdek tür / tanınmayan bir alt tür için "".

    Returns:
        ``STRICT_SUB_GENRES``'ten biri için True.
    """
    return sub_genre in STRICT_SUB_GENRES


def _normalize_text(value: Any) -> str:
    """Deterministik alias eşleştirmesi için yazışma etiketlerini normalize eder."""
    raw_value = value.value if isinstance(value, CorrespondenceType) else str(value)
    raw_value = raw_value.translate(
        str.maketrans(
            {
                "ç": "c",
                "Ç": "C",
                "ğ": "g",
                "Ğ": "G",
                "ı": "i",
                "İ": "I",
                "ö": "o",
                "Ö": "O",
                "ş": "s",
                "Ş": "S",
                "ü": "u",
                "Ü": "U",
            }
        )
    )
    normalized = unicodedata.normalize("NFKD", raw_value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9_]+", " ", ascii_text).strip()


def _match_type(value: Any) -> CorrespondenceType | None:
    """Ham bir değeri desteklenen bir yazışma türüyle eşleştirir."""
    if value is None:
        return None
    if isinstance(value, CorrespondenceType):
        return value

    normalized = _normalize_text(value)
    for correspondence_type, aliases in CORRESPONDENCE_TYPE_ALIASES.items():
        if normalized in aliases:
            return correspondence_type
        if any(
            re.search(rf"\b{re.escape(alias)}\b", normalized)
            for alias in aliases
            if "_" not in alias
        ):
            return correspondence_type
    return None


#: ``GENRE_SURFACES`` (C16) için sol-kelime-sınırlı derlenmiş desenler;
#: ``intent_scorer.ALL_RULES``'ın kendi yüzeyleri için kullandığı aynı
#: derleyici -- sağ tarafta açık, böylece köke doğrudan eklenen bir Türkçe
#: ek ("dilekçe" + "sini" -> "dilekcesini", aralarında boşluk yok) yine de
#: eşleşir. Eski iki-taraflı ``\b...\b`` sınırı, yüzeyin *tüm* kelime
#: olmasını gerektiriyordu: "itiraz dilekcesi", "itiraz dilekçesi yazınız"
#: ile eşleşiyordu ama "itiraz dilekçesine cevap yazınız" (yönelme hâli,
#: yüzey bir önek, tüm kelime değil) ile eşleşmiyordu -- her iki durumda da
#: aynı alt türe çözümlenmesi gereken sıradan, günlük bir ifade biçimi.
_GENRE_PATTERNS_BY_LENGTH: tuple[tuple[re.Pattern[str], CorrespondenceType, str], ...] = tuple(
    (_compile_surface(surface), correspondence_type, sub_genre)
    for surface, correspondence_type, sub_genre in _GENRE_SURFACES_BY_LENGTH
)


def match_genre(user_request: str) -> tuple[CorrespondenceType, str] | None:
    """Kullanıcının kendi taslak isteğini ``GENRE_SURFACES`` ile eşleştirir.

    Her yüzeyi en uzundan başlayarak dener, böylece daha özgül bir ifade
    ("dilekçeye cevap") içerdiği daha kısa bir ifadeye ("dilekçe") her
    zaman üstün gelir.

    Args:
        user_request: Kullanıcının orkestratör boilerplate'i tarafından
            değiştirilmemiş kendi mesajı.

    Returns:
        Eşleşen tür ve alt tür etiketi (bir çekirdek tür için boş), ya da
        hiçbir şey eşleşmezse None.
    """
    normalized = _normalize_text(user_request)
    if not normalized:
        return None
    for pattern, correspondence_type, sub_genre in _GENRE_PATTERNS_BY_LENGTH:
        if pattern.search(normalized):
            return correspondence_type, sub_genre
    return None


def _classification_type(
    classification: dict[str, Any],
) -> CorrespondenceType | None:
    """Classification metadata'sında açıkça istenen bir çıktı türünü çözümler."""
    metadata = classification.get("metadata", {})
    for key in (
        "correspondence_type",
        "response_type",
        "yazisma_turu",
        "yazışma_türü",
    ):
        matched = _match_type(classification.get(key) or metadata.get(key))
        if matched:
            return matched
    return None


def _infer_from_document_type(
    classification: dict[str, Any],
) -> CorrespondenceType | None:
    """Gelen belge sınıflandırmasından en güvenli çıktı türünü çıkarsar.

    Yalnızca yanıtlanacak gerçek bir gelen belge olduğunda anlamlıdır --
    bkz. ``resolve_correspondence_type``'in ``has_source_document`` kapısı.
    Bu olmadan, sınıflandırmada "dilekce" görünmesi, yanıtlanacak bir gelen
    dilekçe olduğu anlamına gelmez, *kullanıcının kendi mesajının* bir
    dilekçe gibi okunduğu (birini yazdırma isteği) anlamına gelir; bundan
    RESPONSE_LETTER çıkarsamak istenen yönü tersine çevirir.
    """
    document_type = classification.get("doc_type") or classification.get(
        "document_type"
    )
    normalized = _normalize_text(document_type or "")

    if "ust yazi" in normalized:
        return CorrespondenceType.COVER_LETTER
    if any(label in normalized for label in ("bilgi notu", "bilgilendirme", "duyuru")):
        return CorrespondenceType.INFORMATION_NOTICE
    if any(
        label in normalized
        for label in (
            "basvuru",
            "cevap yazisi",
            "dilekce",
            "sikayet",
            "soru",
            "talep",
        )
    ):
        return CorrespondenceType.RESPONSE_LETTER
    return None


def resolve_correspondence_type(
    requested_type: Any,
    user_request: str,
    classification: dict[str, Any],
    has_source_document: bool = True,
) -> tuple[CorrespondenceType, str, str]:
    """Çıktı türünü ve alt türünü açık, deterministik bir öncelik sırasıyla çözümler.

    Args:
        requested_type: Workflow çağıranı tarafından sağlanan açık tür
            (bir API seçimi, ya da çözümlenmiş bir yazım-brief cevabı).
        user_request: Kullanıcının kendi taslak isteği, orkestratör
            boilerplate'i asla değil -- bunun yerine boilerplate'i
            eşleştirmek, daha önce her chat kaynaklı taslağın
            RESPONSE_LETTER'a çözümlenmesine neden olan şeydi, çünkü
            boilerplate'in kendisi ("... resmî ve kurumsal bir Türkçe yanıt
            taslağı oluştur.") "yanıt" kelimesini içeriyor.
        classification: Classification Graph sonucu ve metadata.
        has_source_document: Yanıtlanacak gerçek bir gelen belge olup
            olmadığı. Çoğu yalnızca-chat taslak turunda False'tur; bu
            durumda ``_infer_from_document_type``'ı devre dışı bırakır,
            çünkü gelen bir belge olmadan classification'daki "dilekce",
            yanıtlanacak bir şeyin değil, kullanıcının kendi isteğinin bir
            okumasıdır.

    Returns:
        Çözümlenen tür, çözümleme kaynağı ve kullanıcı dört spec'lenmiş
        türün dışında belirli bir tür istediğinde serbest metin bir alt tür
        etiketi ("itiraz dilekçesi") -- aksi hâlde boş string. Bir
        fallback sonucu incelemeyi gerektirir.
    """
    if requested_type is not None:
        matched = _match_type(requested_type)
        if matched:
            # C16: açık bir tür (bir API seçimi, çözümlenmiş bir
            # yazım-brief cevabı), kullanıcının kendi metni daha özgül
            # birini adlandırsa bile ("itiraz dilekçesi yaz" ile birlikte
            # çağıran tarafından sağlanan OTHER_OFFICIAL) eskiden her
            # zaman alt türü düşürürdü -- yalnızca match_genre açık türle
            # uyuştuğunda korunur, böylece çelişkili bir tahmin onu asla
            # geçersiz kılmaz (ör. kendisi OTHER_OFFICIAL'a çözümlenecek
            # bir dilekçe adlandıran metne karşı açık RESPONSE_LETTER).
            sub_genre = ""
            genre_match = match_genre(user_request)
            if genre_match and genre_match[0] == matched:
                sub_genre = genre_match[1]
            return matched, "explicit", sub_genre
        return CorrespondenceType.OTHER_OFFICIAL, "fallback", ""

    genre_match = match_genre(user_request)
    if genre_match:
        matched_type, sub_genre = genre_match
        return matched_type, "user_request", sub_genre

    classified = _classification_type(classification)
    if classified:
        return classified, "classification", ""

    if has_source_document:
        inferred = _infer_from_document_type(classification)
        if inferred:
            return inferred, "document_type", ""

    return CorrespondenceType.OTHER_OFFICIAL, "fallback", ""


def format_correspondence_profile(
    correspondence_type: str, sub_genre: str = ""
) -> str:
    """Çözümlenen türü ve taslak kurallarını agent prompt'ları için biçimlendirir.

    Args:
        correspondence_type: Desteklenen bir CorrespondenceType değeri.
        sub_genre: Kullanıcı çözümlenen türün genel rehberliğinin
            kapsadığından daha özgül bir şey istediğinde, serbest metin bir
            tür etiketi ("itiraz dilekçesi").

    Returns:
        Türkçe tür etiketi ve türe özgü taslak rehberliği; bir alt tür
        ayarlıysa ek bir alt tür satırıyla birlikte.
    """
    resolved = CorrespondenceType(correspondence_type)
    profile = (
        f"{CORRESPONDENCE_TYPE_LABELS[resolved]} (`{resolved.value}`)\n"
        f"Tür Kuralları: {CORRESPONDENCE_TYPE_GUIDANCE[resolved]}"
    )
    if sub_genre:
        profile += (
            f"\nÖzel Tür: {sub_genre} -- bu türün yerleşik yapı, hitap ve kapanış "
            "kalıplarını uygula; genel 'diğer resmî yazışma' şablonuna değil, "
            f"özellikle {sub_genre} biçimine sadık kal."
        )
    return profile
