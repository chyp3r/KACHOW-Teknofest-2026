"""Required-field rules for incoming official documents.

The rules live in Python rather than a data file for three reasons: Pydantic
validates them at import time, they are a closed developer-maintained set (unlike
the legislation *text*, which is editable content under `datasets/mevzuat/`), and
grep/IDE navigation keeps every citation next to the field it justifies.

Article numbers were taken from the official text of the Resmî Yazışmalarda
Uygulanacak Usul ve Esaslar Hakkında Yönetmelik (published on mevzuat.gov.tr):
Başlık m.10, Sayı m.11, Tarih m.12, Konu m.13, Muhatap m.14, İlgi m.15,
Metin m.16, İmza m.17, Ek m.18, Gizlilik dereceli belgeler m.25.
"""

from pydantic import BaseModel, Field

from app.core.enums.document_type import DocumentType

SEVERITY_REQUIRED = "zorunlu"
SEVERITY_ADVISORY = "onerilen"

#: Regulation short names used in citations.
RYUEHY = "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik"
LAW_3071 = "3071 sayılı Dilekçe Hakkının Kullanılmasına Dair Kanun"
LAW_4982 = "4982 sayılı Bilgi Edinme Hakkı Kanunu"

#: Turkish display names for each incoming document type.
DOCUMENT_TYPE_LABELS: dict[DocumentType, str] = {
    DocumentType.OFFICIAL_LETTER: "Resmî Yazı",
    DocumentType.PETITION: "Dilekçe",
    DocumentType.INFORMATION_REQUEST: "Bilgi Edinme Başvurusu",
    DocumentType.COMPLAINT: "Şikayet",
    DocumentType.CIRCULAR: "Genelge",
    DocumentType.DIRECTIVE: "Talimat",
    DocumentType.REPORT: "Rapor",
    DocumentType.MINUTES: "Tutanak",
    DocumentType.LEAVE_REQUEST: "İzin Talebi",
    DocumentType.OTHER: "Diğer",
}


class FieldRule(BaseModel):
    """A single required-or-advisory field requirement for a document type."""

    key: str = Field(description="EvrakField üzerindeki alan adı.")
    label: str = Field(description="Alanın Türkçe adı.")
    severity: str = Field(description="'zorunlu' veya 'onerilen'.")
    mevzuat: str = Field(description="Alanı gerektiren mevzuat ve madde atfı.")
    reason: str = Field(description="Alanın neden gerekli olduğunun açıklaması.")


def _rule(
    key: str, label: str, mevzuat: str, reason: str, severity: str = SEVERITY_REQUIRED
) -> FieldRule:
    """Build a `FieldRule` with a default severity of mandatory.

    Args:
        key: Field name on `EvrakField`.
        label: Turkish display name.
        mevzuat: Legislation citation.
        reason: Short Turkish justification.
        severity: Either `SEVERITY_REQUIRED` or `SEVERITY_ADVISORY`.

    Returns:
        The constructed rule.
    """
    return FieldRule(
        key=key, label=label, severity=severity, mevzuat=mevzuat, reason=reason
    )


# ---------- Shared rule groups ----------
_OFFICIAL_HEADER_RULES: tuple[FieldRule, ...] = (
    _rule(
        "sayi",
        "Sayı",
        f"{RYUEHY} m.11",
        "Belgelerde sayı bulunması zorunludur; belge takibi ve atıf sayı üzerinden yapılır.",
    ),
    _rule(
        "tarih",
        "Tarih",
        f"{RYUEHY} m.12",
        "Tarih, sayı ile aynı satırda yazı alanının en sağında bulunmalıdır.",
    ),
    _rule(
        "konu",
        "Konu",
        f"{RYUEHY} m.13",
        "Konu, belgenin içeriğini özetleyen yan başlık olarak bulunmalıdır.",
    ),
    _rule(
        "muhatap",
        "Muhatap",
        f"{RYUEHY} m.14",
        "Muhatap, belgenin gönderildiği idareyi veya kişiyi belirtir.",
    ),
    _rule(
        "gonderen_kurum",
        "Gönderen idare (başlık)",
        f"{RYUEHY} m.10",
        "Başlık, belgeyi gönderen idarenin adının belirtildiği bölümdür.",
    ),
    _rule(
        "imza_sahibi",
        "İmza sahibi",
        f"{RYUEHY} m.17",
        "Belge, yetkili amir tarafından ad ve soyad belirtilerek imzalanmalıdır.",
    ),
    _rule(
        "imza_unvani",
        "İmza sahibinin unvanı",
        f"{RYUEHY} m.17",
        "İmza bölümünde imzalayanın unvanı da yer almalıdır.",
        SEVERITY_ADVISORY,
    ),
)

_PETITION_RULES: tuple[FieldRule, ...] = (
    _rule(
        "basvuran_adi",
        "Başvuranın adı ve soyadı",
        f"{LAW_3071} m.4",
        "Dilekçede dilekçe sahibinin adı ve soyadı bulunması gerekir.",
    ),
    _rule(
        "imza_sahibi",
        "İmza",
        f"{LAW_3071} m.4",
        "Dilekçede dilekçe sahibinin imzası bulunması gerekir.",
    ),
    _rule(
        "adres",
        "İş veya ikametgâh adresi",
        f"{LAW_3071} m.4",
        "Dilekçede iş veya ikametgâh adresinin bulunması gerekir.",
    ),
    _rule(
        "konu",
        "Konu",
        f"{RYUEHY} m.13",
        "Talebin konusu açıkça belirtilmelidir.",
    ),
    _rule(
        "tarih",
        "Tarih",
        f"{RYUEHY} m.12",
        "Başvurunun tarihi, süre hesaplarında esas alınır.",
        SEVERITY_ADVISORY,
    ),
)

_INFORMATION_REQUEST_RULES: tuple[FieldRule, ...] = (
    _rule(
        "basvuran_adi",
        "Başvuranın adı ve soyadı",
        f"{LAW_4982} m.6",
        "Bilgi edinme başvurusunda başvuru sahibinin adı ve soyadı bulunmalıdır.",
    ),
    _rule(
        "imza_sahibi",
        "İmza",
        f"{LAW_4982} m.6",
        "Bilgi edinme başvurusunda başvuru sahibinin imzası bulunmalıdır.",
    ),
    _rule(
        "adres",
        "Oturma yeri veya iş adresi",
        f"{LAW_4982} m.6",
        "Bilgi edinme başvurusunda oturma yeri veya iş adresi bulunmalıdır.",
    ),
    _rule(
        "konu",
        "İstenen bilgi veya belge",
        f"{LAW_4982} m.6",
        "Başvuruda istenen bilgi veya belgenin açıkça belirtilmesi gerekir.",
    ),
    _rule(
        "iletisim",
        "İletişim bilgisi",
        f"{RYUEHY} m.24",
        "Başvuru sonucunun iletilebilmesi için iletişim bilgisi önerilir.",
        SEVERITY_ADVISORY,
    ),
)


REQUIRED_FIELD_RULES: dict[DocumentType, tuple[FieldRule, ...]] = {
    DocumentType.OFFICIAL_LETTER: _OFFICIAL_HEADER_RULES,
    DocumentType.CIRCULAR: _OFFICIAL_HEADER_RULES,
    DocumentType.DIRECTIVE: _OFFICIAL_HEADER_RULES,
    DocumentType.PETITION: _PETITION_RULES,
    DocumentType.COMPLAINT: _PETITION_RULES,
    DocumentType.INFORMATION_REQUEST: _INFORMATION_REQUEST_RULES,
    DocumentType.LEAVE_REQUEST: (
        _rule(
            "basvuran_adi",
            "Talep sahibinin adı ve soyadı",
            f"{LAW_3071} m.4",
            "İzin talebinde talep sahibinin adı ve soyadı bulunmalıdır.",
        ),
        _rule(
            "konu",
            "Konu",
            f"{RYUEHY} m.13",
            "Talebin konusu ve izin türü açıkça belirtilmelidir.",
        ),
        _rule(
            "tarih",
            "Tarih",
            f"{RYUEHY} m.12",
            "İzin talebinin tarihi, izin süresinin hesaplanması için gereklidir.",
        ),
        _rule(
            "imza_sahibi",
            "İmza",
            f"{LAW_3071} m.4",
            "Talep, talep sahibi tarafından imzalanmalıdır.",
        ),
    ),
    DocumentType.MINUTES: (
        _rule(
            "tarih",
            "Tarih",
            f"{RYUEHY} m.12",
            "Tutanağın düzenlendiği tarih bulunmalıdır.",
        ),
        _rule(
            "konu",
            "Konu",
            f"{RYUEHY} m.13",
            "Tutanağın konusu açıkça belirtilmelidir.",
        ),
        _rule(
            "imza_sahibi",
            "İmza sahibi",
            f"{RYUEHY} m.17",
            "Tutanak, düzenleyen görevliler tarafından imzalanmalıdır.",
        ),
    ),
    DocumentType.REPORT: (
        _rule(
            "konu",
            "Konu",
            f"{RYUEHY} m.13",
            "Raporun konusu açıkça belirtilmelidir.",
        ),
        _rule(
            "tarih",
            "Tarih",
            f"{RYUEHY} m.12",
            "Raporun tarihi bulunmalıdır.",
        ),
        _rule(
            "imza_sahibi",
            "İmza sahibi",
            f"{RYUEHY} m.17",
            "Rapor, düzenleyen tarafından imzalanmalıdır.",
        ),
    ),
    # An unrecognised document still gets the minimum identifying fields checked,
    # so an unknown type never silently reports as fully compliant.
    DocumentType.OTHER: (
        _rule(
            "konu",
            "Konu",
            f"{RYUEHY} m.13",
            "Belgenin konusu açıkça belirtilmelidir.",
        ),
        _rule(
            "tarih",
            "Tarih",
            f"{RYUEHY} m.12",
            "Belgenin tarihi bulunmalıdır.",
            SEVERITY_ADVISORY,
        ),
    ),
}


#: Values a language model emits instead of null when a field is absent. Compared
#: after Turkish-aware case folding, so every entry must already be in folded form
#: (lower-case ASCII, punctuation collapsed). Punctuation-only placeholders such as
#: "-" or "N/A" fold to "" and "n a" respectively, so they need no separate entry.
BLANK_VALUE_MARKER: frozenset[str] = frozenset(
    {
        "",
        "yok",
        "n a",
        "na",
        "bilinmiyor",
        "belirtilmemis",
        "belirtilmedi",
        "bulunmuyor",
        "bulunmamaktadir",
        "mevcut degil",
        "bos",
        "null",
        "none",
        "nan",
        "tespit edilemedi",
        "okunamadi",
        "yazilmamis",
    }
)
