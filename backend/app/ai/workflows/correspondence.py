import re
import unicodedata
from typing import Any

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

#: Direction-aware genre surfaces, matched against the user's own drafting
#: request (never against orchestrator boilerplate -- see
#: ``resolve_correspondence_type``'s ``user_request`` argument). Each entry
#: is ``(surface, type, sub_genre_label)``. A sub_genre label is a specific
#: document genre ("itiraz dilekçesi") that isn't one of the four spec'd
#: CorrespondenceType values -- it still resolves to OTHER_OFFICIAL, but the
#: label itself is carried into the writer prompt (see
#: ``format_correspondence_profile``) so the output is actually shaped like
#: that genre instead of a generic "diğer resmî yazışma".
#:
#: Includes counter-direction surfaces ("dilekçeye cevap") that outrank a
#: bare genre noun ("dilekçe") by being longer and more specific --
#: "dilekçeye cevap yaz" means *reply to* a petition (a response_letter),
#: the opposite of "dilekçe yaz" (author one, an other_official sub-genre).
#: Matching tries every surface longest-first (see ``match_genre``) so the
#: more specific phrase always wins over the substring it contains, with no
#: separate "counter-signal" bookkeeping needed.
GENRE_SURFACES: tuple[tuple[str, CorrespondenceType, str], ...] = (
    # Counter-direction: "reply to a petition/objection/application" is a
    # response_letter, not the petition itself.
    ("dilekceye cevap", CorrespondenceType.RESPONSE_LETTER, ""),
    ("dilekceyi yanitla", CorrespondenceType.RESPONSE_LETTER, ""),
    ("itiraza cevap", CorrespondenceType.RESPONSE_LETTER, ""),
    ("basvuruya cevap", CorrespondenceType.RESPONSE_LETTER, ""),
    ("talebe cevap", CorrespondenceType.RESPONSE_LETTER, ""),
    # Core-type genre nouns (kept in sync with CORRESPONDENCE_TYPE_ALIASES;
    # listed again here so they participate in the same longest-first pass
    # as the sub-genres below instead of a separate lookup with different
    # precedence rules).
    ("cevap yazisi", CorrespondenceType.RESPONSE_LETTER, ""),
    ("yanit yazisi", CorrespondenceType.RESPONSE_LETTER, ""),
    ("cevabini yaz", CorrespondenceType.RESPONSE_LETTER, ""),
    ("ust yazi", CorrespondenceType.COVER_LETTER, ""),
    ("bilgilendirme metni", CorrespondenceType.INFORMATION_NOTICE, ""),
    ("bilgi notu", CorrespondenceType.INFORMATION_NOTICE, ""),
    ("duyuru metni", CorrespondenceType.INFORMATION_NOTICE, ""),
    # Sub-genres: outside the four spec'd types, carried as free-text.
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

#: ``GENRE_SURFACES`` pre-sorted longest-surface-first, computed once at
#: import time rather than resorted on every call.
_GENRE_SURFACES_BY_LENGTH = tuple(
    sorted(GENRE_SURFACES, key=lambda entry: len(entry[0]), reverse=True)
)


def _normalize_text(value: Any) -> str:
    """Normalize correspondence labels for deterministic alias matching."""
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
    """Match a raw value to a supported correspondence type."""
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


def match_genre(user_request: str) -> tuple[CorrespondenceType, str] | None:
    """Match the user's own drafting request against ``GENRE_SURFACES``.

    Tries every surface longest-first, so a more specific phrase ("dilekçeye
    cevap") always wins over a shorter one it contains ("dilekçe").

    Args:
        user_request: The user's own message, unmodified by orchestrator
            boilerplate.

    Returns:
        The matched type and its sub-genre label (empty for a core type), or
        None when nothing matches.
    """
    normalized = _normalize_text(user_request)
    if not normalized:
        return None
    for surface, correspondence_type, sub_genre in _GENRE_SURFACES_BY_LENGTH:
        if re.search(rf"\b{re.escape(surface)}\b", normalized):
            return correspondence_type, sub_genre
    return None


def _classification_type(
    classification: dict[str, Any],
) -> CorrespondenceType | None:
    """Resolve an output type explicitly requested in classification metadata."""
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
    """Infer the safest output type from the incoming document classification.

    Only meaningful when there is an actual incoming document to answer --
    see ``resolve_correspondence_type``'s ``has_source_document`` gate. Without
    it, "dilekce" showing up in classification means the *user's own message*
    reads like a petition (a request to draft one), not that an inbound
    petition exists to reply to, and inferring RESPONSE_LETTER from that
    reverses the requested direction.
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
    """Resolve the output type and sub-genre with explicit, deterministic precedence.

    Args:
        requested_type: Explicit type supplied by the workflow caller (an
            API selection, or a resolved writing-brief answer).
        user_request: The user's own drafting request, never orchestrator
            boilerplate -- matching that instead of this is what previously
            made every chat-initiated draft resolve to RESPONSE_LETTER, since
            the boilerplate itself ("... resmî ve kurumsal bir Türkçe yanıt
            taslağı oluştur.") contains the word "yanıt".
        classification: Classification Graph result and metadata.
        has_source_document: Whether an actual inbound document exists to
            reply to. False in most chat-only drafting turns; gates
            ``_infer_from_document_type`` off in that case, since without an
            inbound document, "dilekce" in the classification is a reading
            of the user's own request, not of something to reply to.

    Returns:
        Resolved type, its resolution source, and a free-text sub-genre
        label ("itiraz dilekçesi") when the user asked for a specific genre
        outside the four spec'd types -- empty string otherwise. A fallback
        result requires review.
    """
    if requested_type is not None:
        matched = _match_type(requested_type)
        if matched:
            return matched, "explicit", ""
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
    """Format the resolved type and its drafting rules for agent prompts.

    Args:
        correspondence_type: A supported CorrespondenceType value.
        sub_genre: A free-text genre label ("itiraz dilekçesi") when the
            user asked for something more specific than the resolved type's
            generic guidance covers.

    Returns:
        Turkish type label and the type-specific drafting guidance, with an
        extra sub-genre line when one is set.
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
