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
    """Infer the safest output type from the incoming document classification."""
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
    instructions: str,
    classification: dict[str, Any],
) -> tuple[CorrespondenceType, str]:
    """Resolve the output type with explicit and deterministic precedence.

    Args:
        requested_type: Explicit type supplied by the workflow caller.
        instructions: User or orchestrator drafting instructions.
        classification: Classification Graph result and metadata.

    Returns:
        Resolved type and its resolution source. A fallback result requires review.
    """
    if requested_type is not None:
        matched = _match_type(requested_type)
        return (
            (matched, "explicit")
            if matched
            else (CorrespondenceType.OTHER_OFFICIAL, "fallback")
        )

    classified = _classification_type(classification)
    if classified:
        return classified, "classification"

    instructed = _match_type(instructions)
    if instructed:
        return instructed, "instructions"

    inferred = _infer_from_document_type(classification)
    if inferred:
        return inferred, "document_type"

    return CorrespondenceType.OTHER_OFFICIAL, "fallback"


def format_correspondence_profile(correspondence_type: str) -> str:
    """Format the resolved type and its drafting rules for agent prompts.

    Args:
        correspondence_type: A supported CorrespondenceType value.

    Returns:
        Turkish type label and the type-specific drafting guidance.
    """
    resolved = CorrespondenceType(correspondence_type)
    return (
        f"{CORRESPONDENCE_TYPE_LABELS[resolved]} (`{resolved.value}`)\n"
        f"Tür Kuralları: {CORRESPONDENCE_TYPE_GUIDANCE[resolved]}"
    )
